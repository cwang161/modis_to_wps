"""
MODIS Data Download Module using Earthaccess
Integrated functionality for downloading MODIS data using NASA's Earthaccess Python library
This module provides a more reliable and official way to access MODIS data compared to web scraping
"""

import os
import sys
import argparse
import re
import numpy as np
import math
import shutil
from pathlib import Path
import earthaccess
import requests
from datetime import datetime, timedelta
import time  # Added missing import
import pickle 
from utils.config import cfg

def download_file(url, output_path, max_retries=3):
    """
    Download a file from a given URL with retry mechanism
    
    Parameters:
    url (str): The URL to download from
    output_path (str): Local path to save the downloaded file
    max_retries (int): Maximum number of download attempts
    
    Returns:
    bool: True if download successful, False otherwise
    """
    for attempt in range(max_retries):
        try:
            # Stream the download to handle large files efficiently
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()  # Raise exception for HTTP errors

            # Write file in chunks to handle large files and save memory
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return True
        except Exception as e:
            print(f"Download attempt {attempt + 1} failed: {e}")
            time.sleep(2)  # Wait before retry
    return False


def get_tile_ids(tile_ids_file, area, dx=0.01, dy=0.01):
    """
    Generate MODIS Tile IDs for the specified geographic area
    MODIS uses a tiling system (hXXvYY) to organize global data
    
    Parameters:
    tile_ids_file (str): Output file to save tile IDs
    area (dict): Geographic area with min/max lon/lat coordinates
    dx (float): Longitudinal resolution buffer
    dy (float): Latitudinal resolution buffer
    
    Returns:
    bool: True if successful, False otherwise
    """
    try:
        print("Generating MODIS Tile IDs for the specified area...")
        
        # Parse area coordinates from dictionary
        LLX, LLY, URX, URY = area['min_lon'], area['min_lat'], area['max_lon'], area['max_lat']
        
        # Expand the domain boundaries slightly to ensure full coverage
        # This accounts for grid alignment and edge effects
        Dom_LLX = math.floor(LLX - dx/2)
        Dom_URX = math.ceil(URX + dx/2)
        Dom_LLY = math.floor(LLY - dy/2)
        Dom_URY = math.ceil(URY + dy/2)

        # Download or use existing MODIS tile boundary definition file
        # This file contains the geographic boundaries of each MODIS tile
        sn_bound_file = os.path.join(Path(__file__).parent.parent, "utils", "sn_bound_10deg.txt")
        if not os.path.exists(sn_bound_file):
            print("Downloading MODIS tile boundary definition file...")
            sn_bound_url = "https://modis-land.gsfc.nasa.gov/pdf/sn_bound_10deg.txt"
            if not download_file(sn_bound_url, sn_bound_file):
                print(f"Error: Cannot download MODIS boundary file {sn_bound_url}")
                return False
            print(f"Successfully downloaded MODIS boundary file: {sn_bound_file}")
 
        # Load tile boundary data, skipping header and footer lines
        data = np.genfromtxt(sn_bound_file, skip_header=7, skip_footer=3)

        # Remove existing tile IDs file if it exists
        if os.path.exists(tile_ids_file):
            os.remove(tile_ids_file)
        
        # Generate tile IDs file by checking which tiles intersect with our area
        with open(tile_ids_file, 'w') as f:
            i = 0
            while i < data.shape[0]:
                # Extract tile boundaries from the data file
                latmin, latmax, lonmin, lonmax = data[i, 4], data[i, 5], data[i, 2], data[i, 3]
                i += 1
                
                # Check if this tile overlaps with our domain
                if (latmax < Dom_LLY or latmin > Dom_URY or 
                    lonmax < Dom_LLX or lonmin > Dom_URX):
                    continue  # Skip tiles that don't overlap
                
                # Extract vertical and horizontal tile indices
                vert = data[i-1, 0]  # Vertical tile number
                horiz = data[i-1, 1]  # Horizontal tile number
                
                # Format tile ID as hXXvYY (e.g., h08v05)
                tile_id = f'h{int(horiz):02d}v{int(vert):02d}'
                f.write(tile_id + '\n')
        
        print(f"Successfully generated MODIS Tile IDs file: {tile_ids_file}")
        return True
            
    except Exception as e:
        print(f"Error generating MODIS Tile IDs: {e}")
        return False

def search_modis_granules(area, data_product, tile_ids_file, start_date, end_date):
    """
    Search for MODIS data granules using Earthaccess API
    Earthaccess provides a more reliable interface than web scraping
    
    Parameters:
    area (dict): Geographic area with min/max lon/lat
    data_product (str): MODIS data product name (e.g., 'MCD19A2')
    tile_ids_file (str): File containing valid tile IDs
    start_date (str): Start date in YYYYMMDD format
    end_date (str): End date in YYYYMMDD format
    
    Returns:
    list: List of granule objects found, or None if error
    """
    try:
        # Read tile IDs from file
        with open(tile_ids_file, 'r') as f:
            tile_list = [line.strip() for line in f if line.strip()]
        
        if not tile_list:
            print("Error: No valid tile IDs found")
            return None
        
        print(f"Searching MODIS data: {data_product}, time range: {start_date} to {end_date}, Tile IDs: {tile_list}")
        
        # Create search patterns for each tile
        # Earthaccess uses readable_granule_name pattern matching
        granule_patterns = [f"{data_product}.*.{tile}.061.*" for tile in tile_list]
        
        # Search for granules using Earthaccess API
        results_all = []
        for granule_pattern in granule_patterns:
            results = earthaccess.search_data(
                short_name=data_product,
                version="061",  # Collection 6.1
                temporal=(start_date, end_date),
                readable_granule_name=granule_pattern
            )
            results_all += results
        
        # Alternative search method using bounding box (commented out)
        '''
        results_all = earthaccess.search_data(
            short_name=data_product,
            version="061",
            temporal=(start_date, end_date),
            bounding_box=(area['min_lon'], area['min_lat'], area['max_lon'], area['max_lat'])
        )
        '''
        
        print(f"Found {len(results_all)} total granules")
        
        return results_all
        
    except Exception as e:
        print(f"Error searching MODIS data: {e}")
        return None


def load_search_cache(cache_file, current_area, current_data_product, current_start_date, current_end_date):
    """
    Load search results from cache file if parameters match
    
    Parameters:
    cache_file (str): Path to cache file
    current_area (dict): Current geographic area
    current_data_product (str): Current data product
    current_start_date (str): Current start date
    current_end_date (str): Current end date
    
    Returns:
    list: Cached results if parameters match, None otherwise
    """
    try:
        if not os.path.exists(cache_file):
            return None
            
        with open(cache_file, 'rb') as f:
            cache_data = pickle.load(f)
        
        # Check if parameters match
        if ((cache_data['area'] == current_area) and
            (cache_data['data_product'] == current_data_product) and
            (cache_data['start_date'] == current_start_date) and
            (cache_data['end_date'] == current_end_date)):
            
            print("Using cached search results")
            return cache_data['results']
        else:
            print("Cache parameters don't match, performing new search")
            return None
            
    except Exception as e:
        print(f"Error loading cache: {e}")
        return None

def download_modis_data(area, data_product, start_date, end_date, username=None, password=None, output_path='./', temp_dir='./', dx=0.01, dy=0.01, **kwargs):
    """
    Main download function - Download MODIS data using Earthaccess library
    This provides a more reliable and official way to access NASA Earthdata
    
    Parameters:
    area (dict): Geographic area dictionary with keys:
                 - min_lon: minimum longitude
                 - min_lat: minimum latitude  
                 - max_lon: maximum longitude
                 - max_lat: maximum latitude
    data_product (str): MODIS data product name (MCD19A2, MOD13A2, MCD12Q1)
    start_date (str): Start date in YYYYMMDD format
    end_date (str): End date in YYYYMMDD format
    username (str): Earthdata login username (optional, will prompt if not provided)
    password (str): Earthdata login password (optional, will prompt if not provided)
    output_path (str): Final output directory for processed files
    temp_dir (str): Temporary working directory for processing
    dx (float): Longitudinal resolution in degrees
    dy (float): Latitudinal resolution in degrees
    
    Returns:
    bool: True if entire process successful, False otherwise
    """
    try:
        # Set Earthdata credentials in environment variables
        # These will be used by the earthaccess library for authentication
        if username:
            os.environ.setdefault("EARTHDATA_USERNAME", username)
        else:
            # Prompt for username if not provided
            username = input("Enter Earthdata username: ")
            os.environ.setdefault("EARTHDATA_USERNAME", username)
        
        if password:
            os.environ.setdefault("EARTHDATA_PASSWORD", password)
        else:
            # Prompt for password if not provided
            password = input("Enter Earthdata password: ")
            os.environ.setdefault("EARTHDATA_PASSWORD", password)

        # Authenticate with Earthdata using environment variables
        # persist=True will cache the authentication for future use
        auth = earthaccess.login(strategy="environment", persist=True)
        if auth.authenticated:
            print("Earthaccess authentication successful")
        else:
            print("Earthaccess authentication failed")
            return False

        # Create output directory structure
        os.makedirs(output_path, exist_ok=True)
        output_modis_dir = os.path.join(output_path, f"MODIS_{data_product}")
        os.makedirs(output_modis_dir, exist_ok=True)
 
        # Create temporary working directories
        os.makedirs(temp_dir, exist_ok=True)
        temp_modis_dir = os.path.join(temp_dir, f"MODIS_{data_product}")
        os.makedirs(temp_modis_dir, exist_ok=True) 

        # Step 1: Generate MODIS Tile IDs for the specified area
        print("Step 1: Generating MODIS Tile IDs...")
        tile_ids_file = os.path.join(temp_dir, "MODIS_TileIDs.txt")
        if not get_tile_ids(tile_ids_file, area, dx, dy):
            print("Error: Failed to generate MODIS Tile IDs")
            return False

        # Earthaccess search is inclusive of end date, so we add one day
        # to ensure we get all granules for the end date
        next_day = datetime.strptime(end_date, "%Y%m%d") + timedelta(days=1)
        new_end_date = next_day.strftime("%Y%m%d") 

        # Step 2: Check for cached search results
        print("Step 2: Checking for cached search results...")
        cache_file = os.path.join(temp_dir, f"modis_search_cache_{data_product}.pkl")
        results_all = load_search_cache(cache_file, area, data_product, start_date, new_end_date)
        if results_all is None:
            # Step 3: Search for MODIS data granules using Earthaccess
            print("Step 3: Searching for MODIS data granules (no cache found)...")
            results_all = search_modis_granules(area, data_product, tile_ids_file, start_date, new_end_date)
            
            if not results_all:
                print("Error: No matching MODIS data found")
                return False
            
            # Save search results to cache file
            print("Saving search results to cache file...")
            try:
                cache_data = {'area': area, 'data_product': data_product, 'start_date': start_date, 
                              'end_date': new_end_date, 'results': results_all}
                with open(cache_file, 'wb') as f:
                     pickle.dump(cache_data, f)
        
                print(f"Search results cached to: {cache_file}")
            except Exception as e:
                print(f"Error saving cache: {e}")


        # Step 4: Filter granules to download only missing files
        print("Step 4: Filtering MODIS files to download only missing files...")
        # Get list of existing files in output directory
        existing_files = set([filename for filename in os.listdir(output_modis_dir) if filename.endswith('.hdf')])
        
        # Filter granules to exclude files that already exist
        filtered_granules = [
            granule for granule in results_all 
            if granule.data_links(access="direct")[0].split('/')[-1] not in existing_files
        ]
        
        # Check if any downloads are needed
        if not filtered_granules:
            print("All MODIS files already exist, no download needed")
        else:
            # Step 5: Download MODIS data using Earthaccess
            print("Step 5: Downloading MODIS data...")
            files = earthaccess.download(filtered_granules, temp_modis_dir)
            if files:
                print(f"MODIS data downloaded to temporary directory: {temp_modis_dir}")
            else:
                print(f"ERROR happens in earthaccess.download")
                return False

            # Move downloaded files from temporary to final output directory
            if output_modis_dir != temp_modis_dir:
                for f in Path(temp_modis_dir).rglob('*.hdf'):
                    shutil.move(str(f), Path(output_modis_dir) / f.name)
                print(f"Moved downloaded files to final output directory: {output_modis_dir}")
        
        # Step 6: Verify download completeness
        print("Step 6: Verifying download completeness...")
        count = len(list(Path(output_modis_dir).rglob('*.hdf')))
        
        if len(results_all) <= count:
            print('Download successful: correct number of files')
            print("Cleaning up temp directories...")
            try:
                # Remove temp directory with original downloaded files
                if os.path.exists(temp_modis_dir):
                    shutil.rmtree(temp_modis_dir, ignore_errors=True)
                    print(f"Removed temp directory: {temp_modis_dir}")
            except Exception as cleanup_error:
                print(f"Warning: Could not completely clean up temporary directories: {cleanup_error}")

            return True
        else:
            # Identify which files failed to download
            existing_files = set([filename for filename in os.listdir(output_modis_dir) if filename.endswith('.hdf')])
            data_links = [granule.data_links(access="direct")[0] for granule in results_all]
            failed_links = [link for link in data_links if link.split('/')[-1] not in existing_files]
            
            # Save failed URLs for manual retry
            failed_link_file = f"{temp_dir}Failed_MODIS_{data_product}_link.txt"
            with open(failed_link_file, "w") as f:
                f.write("\n".join(failed_links))
            
            print(f'Download incomplete: expected {len(results_all)} files, found {count} files')
            print(f'Check {failed_link_file} for missing files and retry manually')
            return False

    except Exception as e:
        print(f"Error in MODIS download process: {e}")
        return False


def main():
    """
    Standalone execution entry point for MODIS download using Earthaccess
    Reads configuration and initiates the download process
    """
    # Parse configuration parameters
    try:
        area = {
            'min_lon': cfg.domains.default.region.min_lon,
            'min_lat': cfg.domains.default.region.min_lat,
            'max_lon': cfg.domains.default.region.max_lon,
            'max_lat': cfg.domains.default.region.max_lat
        }
        
        # Get data product from configuration or use default
        data_product = 'MCD12Q1'
        
        # Get date range from configuration
        start_date = str(cfg.time.str_date)
        end_date = str(cfg.time.end_date)
        
        # Validate date format
        if len(start_date) != 8 or len(end_date) != 8:
            print("Error: Invalid date format in configuration, should be YYYYMMDD")
            return
        
    except Exception as e:
        print(f"Error reading configuration: {e}")
        return

    # Execute the complete download and processing pipeline
    success = download_modis_data(
        area, 
        data_product,
        start_date, 
        end_date,
        getattr(cfg.credentials.earthdata, 'username', None),
        getattr(cfg.credentials.earthdata, 'password', None),
        cfg.paths.download_output + '/landusetype/', 
        cfg.paths.download_temp, 
        cfg.domains.default.resolution.dx, 
        cfg.domains.default.resolution.dy
    )
    
    if success:
        print("MODIS data processing completed successfully using Earthaccess")
    else:
        print("MODIS data processing failed")
        sys.exit(1)  # Exit with error code


if __name__ == "__main__":
    main()
