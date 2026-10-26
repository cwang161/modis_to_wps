#!/usr/bin/env python3
"""
Generic GDAL-based regridding script for various geospatial data preprocessing
Compatible with preprocess.py unified preprocessing framework
Processes one data type at a time with flexible parameters
"""

import os
import sys
import glob
import argparse
import subprocess
import numpy as np
from pathlib import Path
from datetime import datetime
import multiprocessing as mp
from utils.config import cfg
def run_command(cmd, description=""):
    """
    Execute command line command with proper error handling
    
    Parameters:
    -----------
    cmd : list
        Command to execute as list of arguments
    description : str
        Description of the command for logging
    
    Returns:
    --------
    bool
        True if command executed successfully, False otherwise
    """
    if description:
        print(f"Executing: {description}")

    try:
        result = subprocess.run(cmd, capture_output=False, text=True, timeout=3600)
        
        if result.returncode != 0:
            print(f"Error executing command: {result.stderr}")
            return False
        return True
        
    except subprocess.TimeoutExpired:
        print(f"Command timed out: {' '.join(cmd)}")
        return False
    except Exception as e:
        print(f"Error running command: {e}")
        return False

def gdal_regrid(area, dx, dy, input_dir, output_dir, data_type, output_name=None,
                nodata=None, method='bilinear', variable_name=None, 
                long_name=None, units=None, file_extensions=None):
    """
    Generic function for GDAL-based regridding of various geospatial data
    
    Parameters:
    -----------
    area : dict
        Dictionary containing domain boundaries with keys:
        - min_lon: Minimum longitude
        - min_lat: Minimum latitude  
        - max_lon: Maximum longitude
        - max_lat: Maximum latitude
    dx : float
        Target longitude resolution in degrees
    dy : float
        Target latitude resolution in degrees
    input_dir : Path
        Path object pointing to input directory
    output_dir : Path
        Path object pointing to output directory
    output_name : str
        Name of the output NetCDF file
    data_type : str
        Type of data being processed (for logging and metadata)
    nodata : int/float, optional
        No data value for the dataset
    method : str, optional
        Resampling method ('bilinear', 'sum', 'nearest', 'cubic', etc.)
    variable_name : str, optional
        Name for the output variable in NetCDF file
    long_name : str, optional
        Long descriptive name for the variable
    units : str, optional
        Units of the data
    file_extensions : list, optional
        List of file extensions to look for in input directory
    
    Returns:
    --------
    bool
        True if regridding successful, False otherwise
    """
    
    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Default file extensions to look for
    if file_extensions is None:
        file_extensions = ['hgt.zip', '.tif', '.tiff', '.img', '.hdf', '.h5', '.nc', '.grd', '.bil']
    
    # Find input files with specified extensions
    input_files = []
    for ext in file_extensions:
        input_files.extend(list(input_dir.glob(f"*{ext}")))
        input_files.extend(list(input_dir.glob(f"*{ext.upper()}")))
    
    if not input_files:
        print(f"Error: No data files found in {input_dir}")
        print(f"Looking for extensions: {file_extensions}")
        return False
    
    # Convert Path objects to strings for command execution
    input_files_str = [str(p) for p in input_files]
    
    # Construct output file path
    if output_name  is None:
        output_name = '%s_0p01.nc' % data_type
    output_file = output_dir / output_name
    
    # Check if output file already exists
    if output_file.exists():
        print(f"Regridded file already exists, skipping: {output_file}")
        return True
    
    print(f"Processing {data_type} data:")
    print(f"  Input directory: {input_dir}")
    print(f"  Output file: {output_file}")
    print(f"  Number of input files: {len(input_files)}")
    print(f"  Resampling method: {method}")
    print(f"  No data value: {nodata}")
    
    # Extract domain coordinates from area dictionary
    LLX, LLY, URX, URY = area['min_lon'], area['min_lat'], area['max_lon'], area['max_lat']
    
    # Build GDAL warp command for regridding
    cmd = [
        'gdalwarp', 
        '-overwrite',
        '-of', 'netcdf',           # Output format: NetCDF
        '-co', 'FORMAT=NC4',       # NetCDF4 format
        '-ot', 'Int32',            # Output data type
        '-r', method,              # Resampling method
        '-t_srs', 'EPSG:4326',     # Target coordinate system: WGS84
        '-te', str(LLX), str(LLY), str(URX), str(URY),  # Target extent
        '-tr', str(dx), str(dy),   # Target resolution
    ]
    
    # Add no data value if specified
    if nodata is not None:
        cmd += ['-srcnodata', str(nodata), '-dstnodata', str(nodata)]
    
    # Add all input files to command
    cmd.extend(input_files_str)
    
    # Add output file to command
    cmd.append(str(output_file))
    
    # Execute GDAL warp command
    if not run_command(cmd, f"Regridding {data_type} data"):
        return False
    
    # Determine variable metadata if not provided
    if variable_name is None:
        variable_name = data_type.capitalize()
    
    if long_name is None:
        long_name = variable_name
    
    if units is None:
        # Default units based on common data types
        units_mapping = {
            'population': 'persons',
            'elevation': 'meters',
            'temperature': 'K',
            'precipitation': 'mm',
            'pressure': 'hPa',
            'humidity': '%',
            'ndvi': 'unitless',
            'aod': 'unitless'
        }
        units = units_mapping.get(data_type.lower(), 'unknown')
    
    # Rename Band1 variable to appropriate name
    rename_cmd = [
        'ncrename', '-h', '-O',
        '-v', f'Band1,{variable_name}',
        str(output_file)
    ]
    
    if not run_command(rename_cmd, f"Renaming variable to {variable_name}"):
        return False
    
    # Add metadata attributes to the variable
    attr_cmd = [
        'ncatted', '-O',
        '-a', f'long_name,{variable_name},o,c,{long_name}',
        '-a', f'units,{variable_name},o,c,{units}',
    ]
    
    
    attr_cmd.append(str(output_file))
    
    if not run_command(attr_cmd, "Adding metadata attributes"):
        return False
    
    print(f"✓ {data_type} data processing completed: {output_file}")
    return True


def main():
    """
    Main function for standalone execution
    Processes a single data type with parameters specified via command line arguments
    """
    try: 
    # Create area dictionary from arguments
        area = {
                'min_lon': cfg.domains.default.region.min_lon,
                'min_lat': cfg.domains.default.region.min_lat,
                'max_lon': cfg.domains.default.region.max_lon,
                'max_lat': cfg.domains.default.region.max_lat
        }

        input_dir = cfg.paths.download_output
        output_dir = cfg.paths.preprocessed_output
        dx = cfg.domains.default.resolution.dx
        dy = cfg.domains.default.resolution.dy

    except Exception as e:
        print(f"Configuration reading error: {e}")
        sys.exit(1)

    input_dir = Path(input_dir) / "elevation" / "srtmv003"
    output_dir = Path(output_dir) / "elevation" / "srtmv003"
    method = 'bilinear'
    standard_name = 'elevation'
    no_data = -32768
    
    print("=" * 60)
    print("Generic GDAL Data Preprocessing")
    print("=" * 60)
    print(f"Data type: {standard_name}")
    print(f"Domain: {area}")
    print(f"Resolution: {dx}, {dy}")
    print(f"Input path: {input_dir}")
    print(f"Output path: {output_dir}")
    print(f"No data value: {no_data}")
    print(f"Resampling method: {method}")
    print("=" * 60)

    # Process data type with all parameters
    success = gdal_regrid(
        area=area,
        dx=dx,
        dy=dy,
        input_dir=input_dir,
        output_dir=output_dir,
        data_type=standard_name,
        nodata=no_data,
        method=method,
    )

    # Display result
    print("\n" + "=" * 60)
    print("Processing Result")
    print("=" * 60)
    
    status = "✓ Success" if success else "✗ Failed"
    print(f"{standard_name}: {status}")

    print("=" * 60)
    if success:
        print(f"{standard_name} data preprocessing completed!")
    else:
        print(f"{standard_name} data preprocessing failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
