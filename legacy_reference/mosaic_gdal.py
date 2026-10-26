"""
MODIS Data Mosaicking Processing Script
Function: Process MODIS HDF format data, including data reading, quality assessment, mosaic, reprojection and resampling
"""

from osgeo import gdal, ogr, osr  # GDAL library for geospatial data processing
import numpy as np  # Numerical computing library
import os  # Operating system interface
import sys  # System-related functions
from multiprocessing import Pool  # Multi-processing
from datetime import datetime  # Date and time processing
from dateutil.relativedelta import relativedelta  # Date calculations
import argparse  # Command line argument parsing
from utils.config import cfg  # Configuration file
from pathlib import Path  # Path handling
import subprocess
# Check GDAL version compatibility
try:
    from packaging.version import Version  # Version comparison
except ImportError:
    print("Please install packaging library: pip install packaging")
    sys.exit(1)

def GetExtent(ds):
    """
    Extract geographic extent and geotransform parameters from GDAL dataset.
    
    Parameters:
    -----------
    ds : gdal.Dataset
        Input GDAL dataset
        
    Returns:
    --------
    tuple
        (xmin, ymin, xmax, ymax, xpixel, ypixel, xskew, yskew) or None if error occurs
    """
    try:
        # Get geotransform parameters: upper left x, x pixel size, x rotation, 
        # upper left y, y rotation, y pixel size (usually negative)
        geotransform = ds.GetGeoTransform()
        xmin, xpixel, xskew, ymax, yskew, ypixel = geotransform
        width, height = ds.RasterXSize, ds.RasterYSize  # Get raster dimensions
        xmax = xmin + width * xpixel  # Calculate lower right x coordinate
        ymin = ymax + height * ypixel  # Calculate lower right y coordinate
        
        return xmin, ymin, xmax, ymax, xpixel, ypixel, xskew, yskew
        
    except Exception as e:
        print(f"Error: Failed to get extent from dataset: {e}")
        return None

def dec2bin_bitwise(x, n):
    """
    Convert decimal array to binary array using bitwise operations for QA data interpretation(MSB).
    
    Parameters:
    -----------
    x : numpy.ndarray
        Input decimal array
    n : int
        Number of bits to convert
        
    Returns:
    --------
    numpy.ndarray
        Binary array with shape (original_shape, n) or None if error occurs
    """
    try:
        shp = x.shape  # Save original array shape
        # Use bitwise operations to convert decimal numbers to binary arrays
        # ravel() flattens array, [:,None] adds new axis for broadcasting
        # 1 << np.arange(n) creates bit masks for each bit position
        # & operation extracts individual bits, >0 converts to boolean
        # astype(np.uint8) converts to 0/1 values, reshape restores original shape with added bit dimension
        return np.fliplr((x.ravel()[:,None] & (1 << np.arange(n))) > 0).astype(np.uint8).reshape((*shp, n))
    except Exception as e:
        print(f"Error: Failed to convert decimal to binary: {e}")
        return None

def mosaic(filelist, newfile, varname, QAname, data_product, LLX, LLY, URX, URY, DX, DY, resample_method, no_data, QA_mask=True):
    """
    Mosaic, reproject and resample multiple HDF files into a single output file.
    
    Parameters:
    -----------
    filelist : list
        List of input HDF file paths
    newfile : str
        Base output filename (without extension)
    varname : str
        Variable name in HDF files
    QAname : str
        Quality assessment variable name
    data_product : str
        MODIS data product name (e.g., 'MCD19A2', 'MOD13A2')
    LLX, LLY, URX, URY : float
        Output bounding box coordinates
    DX, DY : float
        Output resolution in degrees
    resample_method : str
        Resampling method ('bilinear', 'nearest', etc.)
    no_data : float or None
        No data value, if None will try to read from file metadata
    QA_mask : bool, optional
        Whether to apply QA masking (default: True)
        
    Returns:
    --------
    bool
        True if successful, False otherwise
    """
    try:
        if not filelist:
            print("Error: Empty file list provided to mosaic function")
            return False

        # Extract date string from filename for logging and identification
        date_str = newfile.split('/')[-1].split('_')[-1][1:]
        
        # Check if output file already exists to avoid redundant processing
        if os.path.exists(newfile+'.nc'):
            print(f"Mosaic file for date {date_str} already exists, skipping duplicate operation")
            return True
        
        # Get spatial extent from first file to determine output mosaic bounds
        g = gdal.Open(f'HDF4_EOS:EOS_GRID:"{filelist[0]}":{varname}')
        extent_result = GetExtent(g)
        extremeleft, _, _, extremeup, xpixel, ypixel, xskew, yskew = extent_result
        
        # Get spatial extent from last file to determine full mosaic bounds
        g = gdal.Open(f'HDF4_EOS:EOS_GRID:"{filelist[-1]}":{varname}')
        extent_result = GetExtent(g)
        _, extremedown, extremeright, _, xpixel, ypixel, xskew, yskew = extent_result
        # Create empty array to store mosaic output with calculated dimensions
        # Calculate array dimensions based on extent and pixel size
        sds = np.full((round((extremedown-extremeup)/ypixel), 
                      round((extremeright-extremeleft)/xpixel)), np.nan)

        # Process each HDF file in the list
        for filename in filelist:
            # Construct dataset names for main variable and QA data
            dataset_name = f'HDF4_EOS:EOS_GRID:"{filename}":{varname}'
            QA_name = f'HDF4_EOS:EOS_GRID:"{filename}":{QAname}'
            
            # Open and read main variable dataset
            g = gdal.Open(dataset_name)
            osds = g.ReadAsArray()  # Read data as numpy array
            
            # Open and read QA dataset
            q = gdal.Open(QA_name)
            qa = q.ReadAsArray()
            
            # Get fill value from metadata, handle different data types
            if no_data is None:
                try:
                    fv = g.GetMetadata()['_FillValue']
                    fv = int(fv) if '.' not in fv else float(fv)
                except:
                    print('Did not find _FillValue in attribute, please provide no_data into the mosaic_gdal.py')
                    return False
            else:
                fv = no_data
            
            # Get valid range from metadata and create validity mask
            try:
                valid_down, valid_up = g.GetMetadata()['valid_range'].split(',')
                valid_down = int(valid_down) if '.' not in valid_down else float(valid_down)
                valid_up = int(valid_up) if '.' not in valid_up else float(valid_up)
                # Create mask for values outside valid range or equal to fill value
                condition_valid = np.less(osds, valid_down) | np.greater(osds, valid_up) | np.equal(osds, fv)
            except:
                # If no valid range specified, only mask fill values
                condition_valid = np.equal(osds, fv)
            
            # Interpret QA bits and create QA-based mask
            # Handle GDAL version compatibility for MOD13A2 product
            # GDAL < 3.7.0 will incorrectly return 8-bit unsigned integer (UInt8) as 16-bit signed (Int16) when reading HDF-EOS products.
            if (Version(gdal.__version__) < Version('3.7.0')) and (data_product == 'MOD13A2'):
                qa = qa.astype(np.int8)
            # Convert QA values to binary arrays for bitwise interpretation
            #qa_bits  = dec2bin_bitwise(qa, qa.dtype.itemsize * 8)
            # Define QA filtering conditions based on product type
            if data_product == 'MOD13A2':
                # For MCD19A2 (Aerosol Optical Depth), check bits 8-11 for quality
                vi_quality = qa & 0xFF
                condition_qa = (vi_quality == 0) | (vi_quality == 1)

            elif data_product == 'MCD19A2':
                aod_qa = (qa >> 8) & 0xF
                condition_qa = (aod_qa == 0)

            else:
                condition_qa = np.ones_like(osds, dtype=bool)

            '''
            if data_product == 'MCD19A2':
                # For MCD19A2 (Aerosol Optical Depth), check bits 8-11 for quality
                condition_qa = (qa_bits[...,-12:-8] == [0,0,0,0]).all(axis=(-1)) # because the bits read from the right side
            elif data_product == 'MOD13A2':
                # For MOD13A2 (Vegetation Index), check first 8 bits for quality, qa.shape is (1200,1200,8)
                condition_qa = (qa_bits[...,-8:0] == [0,0,0,0,0,0,0,0]).all(axis=(-1)) | \
                              (qa_bits[...,-8:0] == [0,0,0,0,0,0,0,1]).all(axis=(-1))
            else:
                # Default: accept all pixels if product type not specified
                condition_qa = np.ones_like(osds, dtype=bool)
            '''
            if QA_mask:
                # Combine validity and QA conditions to create final mask
                condition = condition_valid | ~condition_qa
            else:
                condition = condition_valid
            # Apply mask to data using numpy masked array
            osds = np.ma.masked_array(osds, mask=condition)
            
            # Apply offset correction if specified in metadata
            try:
                add_offset = float(g.GetMetadata().get('add_offset', 0))
                osds = osds - add_offset
            except:
                pass  # Skip if no offset or conversion error
            
            # Apply scale factor correction if specified in metadata
            try:
                scale_factor = float(g.GetMetadata().get('scale_factor', 1))
                # Special handling for MOD13A2 scale factor
                if data_product == 'MOD13A2':
                    scale_factor = 1 / scale_factor
                osds = osds * scale_factor
            except:
                pass  # Skip if no scale factor or conversion error
            
            # Calculate mean for multi-band data (e.g., daily composites)
            if len(osds.shape) == 3:
                osds_mean = osds.mean(axis=0)  # Average across bands
            elif len(osds.shape) == 2 or len(osds.shape) == 1:
                osds_mean = osds[:]  # Single band data
            else:
                print('The size of data is more than 3-dimension, beyond the processing range')
                return False

            # Fill masked values with fill value for output
            osds_mean = osds_mean.filled(fill_value=fv)
            
            # Calculate position of current tile in mosaic output array
            sh = osds_mean.shape  # Current tile dimensions
            # Get geotransform for current tile
            ulx, xres, xskew, uly, yskew, yres = g.GetGeoTransform()
            
            # Calculate relative position in mosaic array
            y = (extremeup - uly) / (extremeup - extremedown)
            x = (ulx - extremeleft) / (extremeright - extremeleft)
            
            # Convert relative position to array indices
            y = round(y * sds.shape[0])
            x = round(x * sds.shape[1])
            
            # Insert current tile data into mosaic array
            sds[y:y+sh[0], x:x+sh[1]] = osds_mean
        
        # Replace any remaining NaN values with fill value
        sds[np.isnan(sds)] = fv
        
        # Determine output data type, handle uint8 special case
        datatype = str(osds.dtype)
        datatype = 'byte' if datatype == 'uint8' else datatype
        
        # Create GeoTIFF output file with appropriate parameters
        ras = gdal.GetDriverByName('GTiff').Create(newfile + '.tif', 
                                                  sds.shape[1], sds.shape[0], 1, 
                                                  gdal.GetDataTypeByName(datatype))
        # Set geotransform parameters
        ras.SetGeoTransform((extremeleft, xpixel, xskew, extremeup, yskew, ypixel))
        
        # Set projection from source dataset
        proj = g.GetProjection()
        source_srs = osr.SpatialReference()
        source_srs.ImportFromProj4(proj)
        ras.SetProjection(source_srs.ExportToWkt())
        
        # Write data to raster band and set metadata
        b = ras.GetRasterBand(1)
        b.WriteArray(sds)
        b.SetDescription(varname)  # Set band description
        b.SetNoDataValue(fv)  # Set no data value
        ras.FlushCache()  # Ensure data is written to disk
        
        # Reproject and resample to target coordinate system and resolution
        out = gdal.Warp(newfile + '.nc', ras, dstSRS='EPSG:4326',  # WGS84 projection
                       outputBounds=(LLX, LLY, URX, URY),  # Output bounds
                       xRes=DX, yRes=DY,  # Target resolution
                       srcNodata=fv, dstNodata=fv,  # No data handling
                       resampleAlg=resample_method,  # Resampling method
                       format='netCDF')  # Output format
        
        # Clean up GDAL objects to free memory
        ras, out = None, None
        
        # Rename variable in netCDF file to match original variable name
        os.system(f'ncrename -O -h -v Band1,{varname} {newfile}.nc')
        
        # Add long_name attribute if available in source metadata
        try:
            long_name = g.GetMetadata()['long_name'].strip('\x00')  # Remove null characters
            os.system(f'ncatted -O -a long_name,{varname},o,c,"{long_name}" {newfile}.nc')
        except:
            pass  # Skip if long_name not available
        
        # Clean up temporary GeoTIFF file
        if os.path.exists(newfile + '.tif'):
            os.remove(newfile + '.tif')
        
        print(f"Mosaic completed for date {date_str}") 
        return True
        
    except Exception as e:
        print(f"Error during mosaic for {date_str}: {e}")
        return False

def multi_mosaic(dayID, hdf_files, ndays, out_dir, varname, QAname, data_product, LLX, LLY, URX, URY, DX, DY, resample_method, no_data, QA_mask=True):
    """
    Multi-process mosaicing processing function for handling multiple days in parallel.
    
    Parameters:
    -----------
    dayID : list
        [start_index, end_index] of days to process
    hdf_files : list
        List of all HDF file paths
    ndays : list
        List of day identifiers
    out_dir : str
        Output directory path
    varname : str
        Variable name in HDF files
    QAname : str
        Quality assessment variable name
    data_product : str
        MODIS data product name
    LLX, LLY, URX, URY : float
        Output bounding box coordinates
    DX, DY : float
        Output resolution
    resample_method : str
        Resampling method
    no_data : float
        No data value
    QA_mask : bool
        Whether to apply QA masking
        
    Returns:
    --------
    bool
        True if successful, False otherwise
    """
    try:
        for day_index in range(dayID[0], dayID[-1]):
            nday = ndays[day_index]  # Get current day identifier
            # Find all files for this specific day
            lfile = sorted([nfile for nfile in hdf_files if nday in nfile])
            
            if lfile:
                # Create output file path
                output_file = os.path.join(out_dir, f"{data_product}_{nday}")
                # Process mosaick for this day
                result = mosaic(lfile, output_file, varname, QAname, data_product, 
                                LLX, LLY, URX, URY, DX, DY, resample_method, no_data, QA_mask=QA_mask)
                if not result:
                    print(f"Error: Mosaick failed for day {nday}")
                    return False

        return True

    except Exception as e:
        print(f"Error in multi_mosaic: {e}")
        return False
    

def process_modis_data(hdf_dir, out_dir, data_product, varname, QAname, output_filename, area, DX=0.01, DY=0.01, resample_method='bilinear', no_data=None, var_newname=None, NP_ava=1, QA_mask=True):
    """
    Main function for processing MODIS HDF data through mosaicking, reprojection and resampling.
    
    Parameters:
    -----------
    hdf_dir : str or Path
        Input directory containing HDF files
    out_dir : str or Path
        Output directory for processed files
    data_product : str
        MODIS data product name (e.g., 'MCD19A2', 'MOD13A2')
    varname : str
        Variable name in HDF files
    QAname : str
        Quality assessment variable name
    output_filename : str
        Base output filename
    area : dict
        Dictionary with 'min_lon', 'min_lat', 'max_lon', 'max_lat' keys
    DX, DY : float, optional
        Output resolution in degrees (default: 0.01)
    resample_method : str, optional
        Resampling method (default: 'bilinear')
    no_data : float, optional
        No data value (default: None, read from metadata)
    NP_ava : int, optional
        Number of parallel processes (default: 1)
    QA_mask : bool, optional
        Whether to apply QA masking (default: True)
        
    Returns:
    --------
    bool
        True if processing successful, False otherwise
    """
    try: 
        # Check if final output file already exists
        if os.path.exists(out_dir / (output_filename + '.nc')):
            print(f"Mosaic file for {data_product} already exists, skipping processing")
            return True
         
        # Extract area boundaries from area dictionary
        LLX, LLY, URX, URY = area['min_lon'], area['min_lat'], area['max_lon'], area['max_lat']
        # Create output directory if it doesn't exist
        os.makedirs(out_dir, exist_ok=True)
        
        # Find all HDF files in input directory
        hdf_files = [str(f) for f in Path(hdf_dir).glob('*.hdf')]
        if not hdf_files:
            print(f"Error: No HDF files found in {hdf_dir}")
            return False
        
        # Extract unique day identifiers from filenames
        ndays = sorted(list(set([os.path.basename(f).split('.')[1] for f in hdf_files])))
        if not ndays:
            print(f"Error: No valid day identifiers found in HDF files from {hdf_dir}")
            return False

        # Determine number of parallel processes to use
        if len(ndays) < NP_ava:
            NP_ava_nc = len(ndays)  # Use fewer processes if fewer days
        else:
            NP_ava_nc = NP_ava  # Use specified number of processes
        
        print(f"Using {NP_ava_nc} CPUs for mosaic processing")
        print('Mosaic in progress...')
 
        # Multi-processing mode
        if NP_ava_nc > 1:
            pool = Pool(NP_ava_nc)  # Create process pool
            grid = len(ndays)  # Total number of days to process
            chunk_size = grid // NP_ava_nc  # Days per process
            # Create intervals for each process
            intervals = [[p*chunk_size, p*chunk_size+chunk_size] for p in range(NP_ava_nc)]
            intervals[-1][1] = max(intervals[-1][1], grid)  # Adjust last interval

            results = []
            # Start processing for each interval
            for dayID in intervals:
                results.append(pool.apply_async(multi_mosaic, 
                    args=(dayID, hdf_files, ndays, out_dir, varname, QAname, data_product, 
                          LLX, LLY, URX, URY, DX, DY, resample_method, no_data, QA_mask)))
            
            pool.close()
            pool.join()
            
            # Check results from all processes
            for result in results:
                if not result.get():
                    print("Error: One or more mosaic tasks failed")
                    return False
        else:
            # Single process mode
            for nday in ndays:
                # Find files for current day
                lfile = sorted([nfile for nfile in hdf_files if nday in nfile])
                if lfile:
                    output_file = os.path.join(out_dir, f"{data_product}_{nday}")
                    # Process mosaic for this day
                    success = mosaic(lfile, output_file, varname, QAname, data_product, 
                                     LLX, LLY, URX, URY, DX, DY, resample_method, no_data, QA_mask=QA_mask)
                    if not success:
                        print(f"Error: Mosaic failed for day {nday}")
                        return False

        # Aggregate all daily files and add time dimension
        outfiles = [str(f) for f in Path(out_dir).glob(f"{data_product}*.nc")]
        
        if outfiles:
            # Create time values for each day
            Times = []
            for nday in ndays:
                # Convert day identifier to datetime object (e.g., "A2008001" -> 2008-01-01)
                date_obj = datetime.strptime(nday[1:], "%Y%j")
                # Convert to hours since 1900-01-01 (CF convention)
                time_hours = (date_obj - datetime(1900, 1, 1)).total_seconds() / 3600
                Times.append(str(int(time_hours)))
            
            if Times:
                # Use NCO tools to concatenate files and add time dimension
                temp_file = os.path.join(out_dir, output_filename + '_inter.nc')
                final_file = os.path.join(out_dir, output_filename + '.nc')
                # Concatenate files along time dimension
                result = subprocess.run(f'ncecat -u time {" ".join(outfiles)} {temp_file}', 
                       shell=True, capture_output=True, text=True)
                if result.returncode != 0:
                    raise Exception(f"ncecat failed: {result.stderr}")
                # Add time coordinate variable
                result = subprocess.run(f'ncap2 -O -s "time[time]={{{",".join(Times)}}}" {temp_file} {final_file}', 
                                       shell=True, capture_output=True, text=True)
                if result.returncode != 0:
                    raise Exception(f"ncap2 failed: {result.stderr}")
                # Add time units attribute
                result = subprocess.run(f'ncatted -O -a units,time,o,c,"hours since 1900-01-01 00:00:00.0" {final_file}', 
                                       shell=True, capture_output=True, text=True)
                if result.returncode != 0:
                    raise Exception(f"ncatted failed: {result.stderr}")
                # Change varible name
                result = subprocess.run(f'ncrename -O -v {varname},{var_newname} {final_file}', 
                                       shell=True, capture_output=True, text=True)
                if result.returncode != 0:
                    raise Exception(f"ncrename failed: {result.stderr}") 
                # Clean up temporary files
                for f in outfiles:
                    os.remove(f)  # Remove individual daily files
                if os.path.exists(temp_file):
                    os.remove(temp_file)  # Remove intermediate file


                print(f"Processing completed: {final_file}")
                return True
    
        return False

    except Exception as e:
        print(f"Error: Unexpected error in process_modis_data: {e}")
        return False

def main():
    """
    Main function for standalone execution or testing of MODIS data processing.
    """
    try:
        
        area = {
            'min_lon': cfg.domains.default.region.min_lon,
            'min_lat': cfg.domains.default.region.min_lat,
            'max_lon': cfg.domains.default.region.max_lon,
            'max_lat': cfg.domains.default.region.max_lat
        }
        
        dx = cfg.domains.default.resolution.dx
        dy = cfg.domains.default.resolution.dy
        input_dir = cfg.paths.download_output
        output_dir = cfg.paths.preprocessed_output
        
    except Exception as e:
        print(f"Configuration error: {e}")
        sys.exit(1)
   
    data_product = 'MCD19A2'
    input_dir = Path(input_dir) / "aod" / f"MODIS_{data_product}"
    output_dir = Path(output_dir) / "aod" / f"MODIS_{data_product}"
    method = 'bilinear'
    varname, QAname, output_filename  = 'grid1km:Optical_Depth_055', 'grid1km:AOD_QA', 'aod_0p1'
    #varname, QAname, output_filename = 'MODIS_Grid_16DAY_1km_VI:"1 km 16 days NDVI"','MODIS_Grid_16DAY_1km_VI:"1 km 16 days pixel reliability"', 'ndvi_0p1'
    #varname, QAname, output_filename = 'MODIS_Grid_16DAY_1km_VI:"1 km 16 days pixel reliability"','MODIS_Grid_16DAY_1km_VI:"1 km 16 days pixel reliability"', 'ndvi_qa_0p1'
    #varname, QAname, output_filename = 'MCD12Q1:LC_Type1', 'MCD12Q1:QC' , 'landusetype_0p01'

    print("=" * 60)
    print("Generic MODIS Data Preprocessing")
    print("=" * 60)
    print(f"Data type: {data_product}")

    print(f"Domain: {area}")
    print(f"Resolution: {dx}, {dy}")
    print(f"Input path: {input_dir}")
    print(f"Output path: {output_dir}")
    print(f"Resampling method: {method}")
    print("=" * 60)
 
    # Example: Process AOD data
    success = process_modis_data(
        hdf_dir=input_dir,
        out_dir=output_dir,
        data_product=data_product,
        varname=varname,
        QAname=QAname,
        output_filename=output_filename,
        area=area,
        DX=dx,
        DY=dy,
        resample_method=method,
        NP_ava=4,
        QA_mask=False,
    )
    
    if success:
        print("MODIS data processing completed successfully")
    else:
        print("MODIS data processing failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
