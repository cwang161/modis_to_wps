"""
MODIS AOD Data Download Module
Integrated functionality for obtaining Tile IDs, generating download URLs, and downloading MODIS data
MODIS (Moderate Resolution Imaging Spectroradiometer) provides various Earth observation products
This module handles the complete workflow for downloading MODIS data products
Supported products: MCD19A2 (Aerosol), MOD13A2 (Vegetation), MCD12Q1 (Land Cover)
"""

import os
import sys
import subprocess
import argparse
import getpass
import requests
from bs4 import BeautifulSoup
import re
import numpy as np
import math
import shutil
from pathlib import Path
from datetime import datetime, timedelta
import time
from utils.config import cfg
from dateutil.relativedelta import relativedelta

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

def generate_download_urls(urls_file, tile_ids_file, data_product, start_date, end_date):
    """
    Generate download URLs for MODIS data products
    Scrapes the NASA LAADS website to find available files for the specified tiles and date range
    
    Parameters:
    urls_file (str): Output file to write URLs
    tile_ids_file (str): File containing valid tile IDs
    data_product (str): MODIS data product name (e.g., 'MCD19A2')
    start_date (str): Start date in YYYYMMDD format
    end_date (str): End date in YYYYMMDD format
    
    Returns:
    bool: True if URLs generated successfully, False otherwise
    """
    try:
        # Read tile IDs from file
        with open(tile_ids_file, 'r') as file:
            tile_list = [line.strip() for line in file if line.strip()]
        
        if not tile_list:
            print("Error: No valid tile IDs found")
            return False
        
        # Display found tile IDs for user information
        tile_list_str = ' '.join(tile_list)
        print(f"Found {len(tile_list)} valid tile IDs: {tile_list_str}")
        
        # Base URL for MODIS archive
        data_pool = 'https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/61/'
        
        # Parse date range
        start_dt = datetime.strptime(start_date, "%Y%m%d")
        end_dt = datetime.strptime(end_date, "%Y%m%d") + timedelta(days=1)
        if data_product == 'MOD13A2': # prepare for the gap filling of NDVI product
            start_dt = start_dt - timedelta(days=16)
            end_dt = end_dt + timedelta(days=16)
        # Remove existing URL file if it exists
        if os.path.exists(urls_file):
            os.remove(urls_file)
        
        # Generate URLs by iterating through each day in the date range
        with open(urls_file, 'w') as f:
            date = start_dt
            index = 0
            total_urls = 0
            
            while date < end_dt:
                # Format date as Year.DayOfYear (e.g., 2023.123)
                date_str = datetime.strftime(date, "%Y.%j")
                year = date_str.split('.')[0]
                doy = date_str.split('.')[1]
                
                # Construct URL for this specific date
                url = f"{data_pool}{data_product}/{year}/{doy}/"
                try:
                    # Check if data exists for this date
                    reqs = requests.get(url, timeout=30)
                    
                    # Handle special case for MOD13A2 (16-day composite product)
                    if (data_product == 'MOD13A2' and reqs.status_code == 404 and index == 0):
                        date = date - timedelta(days=1)  # Adjust for composite product timing
                        continue
                    
                    if reqs.status_code == 200:
                        # Parse HTML to find all .hdf file links
                        soup = BeautifulSoup(reqs.text, 'html.parser')
                        link_list = [
                            link.get('href') for link in soup.find_all('a') 
                            if link.get('href').endswith(".hdf")
                        ]
                        link_list = set(link_list)  # Remove duplicates
                        
                        # Filter links to only include tiles in our area of interest
                        for link in link_list:
                            filename = link.split('/')[-1]
                            tile_id = filename.split('.')[2]  # Extract tile ID from filename
                            
                            if tile_id in tile_list:
                                f.write(link + '\n')
                                total_urls += 1

                except requests.exceptions.RequestException:
                    print(f"ERROR: Cannot access: {url}")
                    if data_product == 'MCD12Q1':
                        date = date +relativedelta(years=1)
                    else:
                        date = date + timedelta(days=1)
                    continue

                if data_product == 'MCD12Q1':
                    date = date +relativedelta(years=1)
                else:
                    date = date + timedelta(days=1)
                index += 1 # Only make this adjustment on the first pass through the loop (to avoid infinite backoff) for MOD13A2
        
        print(f"Successfully generated {total_urls} MODIS file URLs: {urls_file}")
        return total_urls > 0  # Return True if we found any URLs
        
    except Exception as e:
        print(f"Error generating MODIS download URLs: {e}")
        return False


def download_modis_files(urls_file, output_dir, token=None):
    """
    Download MODIS files using Python requests (without parallel tools)
    Handles authentication, retries, and error handling
    
    Parameters:
    urls_file (str): File containing URLs to download
    output_dir (str): Directory to save downloaded files
    token (str): Earthdata authentication token
    
    Returns:
    bool: True if all downloads successful, False otherwise
    """
    try:
        # Check if URL file exists
        if not os.path.exists(urls_file):
            print("Error: URL file not found")
            return False
        
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        # Read URLs from file
        with open(urls_file, 'r') as f:
            urls = [line.strip() for line in f if line.strip()]
        
        if not urls:
            print("Warning: URL file is empty")
            return False
        
        print(f"Starting download of {len(urls)} files...")
        
        # Create configured session with retry strategy
        session = create_requests_session(token=token)
        
        success_count = 0
        failed_count = 0
        failed_urls = []
        
        # Download each file sequentially
        for i, url in enumerate(urls):
            filename = url.split('/')[-1]
            output_path = os.path.join(output_dir, filename)
            
            print(f"Downloading file {i+1}/{len(urls)}: {filename}")
            
            # Skip if file already exists and has content
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                print(f"File already exists, skipping: {filename}")
                success_count += 1
                continue
            
            # Attempt to download the file
            if download_single_file_modern(session, url, output_path):
                success_count += 1
                print(f"Successfully downloaded: {filename}")
            else:
                failed_count += 1
                failed_urls.append(url)
                print(f"Download failed: {filename}")
            
            # Add small delay to avoid overwhelming the server
            time.sleep(0.5)
        
        # Print download summary
        print(f"Download completed: {success_count} successful, {failed_count} failed")
        
        # Save failed URLs for potential retry
        if failed_urls:
            failed_file = os.path.join(output_dir, "failed_downloads.txt")
            with open(failed_file, 'w') as f:
                f.write("\n".join(failed_urls))
            print(f"Failed URLs saved to: {failed_file}")

        return failed_count == 0  # Return True only if all downloads succeeded
            
    except Exception as e:
        print(f"Error during MODIS download: {e}")
        return False

def create_requests_session(token=None):
    """
    Create a configured requests session with retry strategy and authentication
    
    Parameters:
    token (str): Earthdata authentication token
    
    Returns:
    requests.Session: Configured session object
    """
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    
    # Configure retry strategy for robust downloading
    retry_strategy = Retry(
        total=3,  # Maximum number of retries
        backoff_factor=0.5,  # Exponential backoff between retries
        status_forcelist=[429, 500, 502, 503, 504],  # Retry on these status codes
        allowed_methods=["GET"]  # Only retry GET requests
    )
    
    # Create HTTP adapter with retry configuration
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,  # Connection pool size
        pool_maxsize=10  # Maximum number of connections
    )
    
    # Create and configure session
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # Set request headers including authentication
    session.headers.update({
        'User-Agent': 'MODIS-Downloader/1.0 (Python-Requests)',
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Authorization': f'Bearer {token}' if token else ''
    })
    
    return session

def download_single_file_modern(session, url, output_path, timeout=30):
    """
    Download a single file using modern requests library with progress tracking
    
    Parameters:
    session (requests.Session): Configured session object
    url (str): File URL to download
    output_path (str): Local path to save the file
    timeout (int): Request timeout in seconds
    
    Returns:
    bool: True if download successful, False otherwise
    """
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            # Make HTTP request with streaming
            response = session.get(url, stream=True, timeout=timeout)
            response.raise_for_status()  # Check for HTTP errors
            
            # Get file size from headers (if available)
            total_size = int(response.headers.get('content-length', 0))
            
            # Download file with progress tracking
            with open(output_path, 'wb') as f:
                if total_size == 0:
                    # Unknown file size, write content directly
                    f.write(response.content)
                else:
                    # Download with progress display for large files
                    downloaded = 0
                    chunk_size = 8192  # 8KB chunks
                    
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            # Show progress every 1MB
                            if downloaded % (1024 * 1024) < chunk_size:
                                percent = (downloaded / total_size) * 100
                                print(f"  Progress: {percent:.1f}% ({downloaded}/{total_size} bytes)")
            
            # Verify downloaded file size matches expected size
            if total_size > 0 and os.path.getsize(output_path) != total_size:
                print(f"File size mismatch: expected {total_size}, got {os.path.getsize(output_path)}")
                os.remove(output_path)
                continue
            
            # Additional check: reject files smaller than 100KB (likely errors)
            if os.path.exists(output_path) and os.path.getsize(output_path) < 102400:
                print(f"File size too small (<100KB), deleting: {output_path}")
                os.remove(output_path)
                continue
                
            return True  # Download successful
            
        except requests.exceptions.RequestException as e:
            print(f"Download attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                # Final attempt failed, try fallback method
                return fallback_download_method(url, output_path)
        
        except Exception as e:
            print(f"Unexpected error in download attempt {attempt + 1}: {e}")
            if attempt == max_retries - 1:
                return fallback_download_method(url, output_path)
        
        # Exponential backoff before retry
        time.sleep(2 ** attempt)
    
    return False  # All attempts failed

def fallback_download_method(url, output_path):
    """
    Fallback download method using alternative libraries and tools
    Used when the primary requests-based method fails
    
    Parameters:
    url (str): File URL to download
    output_path (str): Local path to save the file
    
    Returns:
    bool: True if download successful, False otherwise
    """
    try:
        print("Trying fallback download methods...")
        
        # Method 1: Try urllib3 if available
        try:
            import urllib3
            http = urllib3.PoolManager()
            response = http.request('GET', url, preload_content=False)
            
            if response.status == 200:
                with open(output_path, 'wb') as out_file:
                    while True:
                        data = response.read(8192)
                        if not data:
                            break
                        out_file.write(data)
                response.release_conn()
                
                # Validate file size
                if os.path.exists(output_path) and os.path.getsize(output_path) < 102400:
                    print(f"File size too small (<100KB), deleting: {output_path}")
                    os.remove(output_path)
                    return False
                return True
        except ImportError:
            pass  # urllib3 not available
        
        # Method 2: Try system curl command (if available)
        try:
            import subprocess
            result = subprocess.run([
                'curl', '--fail', '-sS', '-L', 
                '-o', output_path, url
            ], capture_output=True, timeout=300)
            
            if result.returncode == 0:
                # Validate file size
                if os.path.exists(output_path) and os.path.getsize(output_path) < 102400:
                    print(f"File size too small (<100KB), deleting: {output_path}")
                    os.remove(output_path)
                    return False
                return True
            else:
                print(f"curl failed: {result.stderr}")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass  # curl not available or timed out
            
        # Method 3: Use built-in urllib as last resort
        try:
            if sys.version_info.major == 2:
                import urllib
                urllib.urlretrieve(url, output_path)
            else:
                from urllib.request import urlretrieve
                urlretrieve(url, output_path)
            
            # Validate file size
            if os.path.exists(output_path) and os.path.getsize(output_path) < 102400:
                print(f"File size too small (<100KB), deleting: {output_path}")
                os.remove(output_path)
                return False
            return True
        except Exception as e:
            print(f"urllib download failed: {e}")
            
        return False  # All fallback methods failed
        
    except Exception as e:
        print(f"Fallback download method failed: {e}")
        # Clean up any partially downloaded invalid file
        if os.path.exists(output_path) and os.path.getsize(output_path) < 102400:
            try:
                os.remove(output_path)
            except:
                pass
        return False



def download_modis_data(area, data_product, start_date, end_date, token=None, output_path='./', temp_dir='./', dx=0.01, dy=0.01, **kwargs):
    """
    Main download function - integrates all MODIS download and processing steps
    Handles the complete workflow from tile ID generation to final file organization
    
    Parameters:
    area (dict): Geographic area dictionary with keys:
                 - min_lon: minimum longitude
                 - min_lat: minimum latitude  
                 - max_lon: maximum longitude
                 - max_lat: maximum latitude
    data_product (str): MODIS data product name (MCD19A2, MOD13A2, MCD12Q1)
    start_date (str): Start date in YYYYMMDD format
    end_date (str): End date in YYYYMMDD format
    token (str): Earthdata authentication token (optional, will prompt if not provided)
    output_path (str): Final output directory for processed files
    temp_dir (str): Temporary working directory for processing
    dx (float): Longitudinal resolution in degrees
    dy (float): Latitudinal resolution in degrees
    
    Returns:
    bool: True if entire process successful, False otherwise
    """
    try:
        # Prompt for token if not provided
        if not token:
            token = getpass.getpass("Enter EarthData token: ")

        # Create output directory structure
        os.makedirs(output_path, exist_ok=True)
        output_modis_dir = os.path.join(output_path, f"MODIS_{data_product}")
        os.makedirs(output_modis_dir, exist_ok=True)
 
        # Create temporary working directories
        os.makedirs(temp_dir, exist_ok=True)
        temp_modis_dir = os.path.join(temp_dir, f"MODIS_{data_product}")
        os.makedirs(temp_modis_dir, exist_ok=True)
    
        # Define file paths for intermediate files
        tile_ids_file = os.path.join(temp_dir, "Download_MODIS_TileIDs.txt")
        urls_file = os.path.join(temp_dir, f"Download_MODIS_{data_product}_URLs.txt")

        # Step 1: Generate MODIS Tile IDs for the specified area
        print("Step 1: Generating MODIS Tile IDs...")
        if not get_tile_ids(tile_ids_file, area, dx, dy):
            print("Error: Failed to generate MODIS Tile IDs")
            return False

        # Step 2: Generate download URLs for the specified date range and tiles
        print("Step 2: Generating MODIS download URLs...")
        if not generate_download_urls(urls_file, tile_ids_file, data_product, start_date, end_date):
            return False
        
        # Step 3: Filter URLs to download only missing files
        print("Step 3: Filtering URL file to download only missing files...")
        
        # Read all generated URLs
        with open(urls_file, 'r') as f:
            all_urls = [line.strip() for line in f if line.strip()]
        
        # Check which files already exist in the output directory
        existing_files = set(os.listdir(output_modis_dir))
        
        # Filter URLs to exclude files that already exist
        filtered_urls = []
        for url in all_urls:
            filename = url.split('/')[-1]
            if filename not in existing_files:
                filtered_urls.append(url)
            else:
                print(f"File already exists, skipping: {filename}")
        
        # Check if any downloads are needed
        if not filtered_urls:
            print("All MODIS files already exist, no download needed")
        else: 
            # Write filtered URLs to a new file
            filtered_urls_file = os.path.join(temp_dir, f"Download_MODIS_{data_product}_URLs_filtered.txt")
            with open(filtered_urls_file, 'w') as f:
                for url in filtered_urls:
                    f.write(url + '\n')
            print(f"Filtered download list: {len(filtered_urls)}/{len(all_urls)} files to download")
                
            # Step 4: Download MODIS data using the filtered URL list
            print("Step 4: Downloading MODIS data...")
            download_success = download_modis_files(filtered_urls_file, temp_modis_dir, token=token)
            
            # Step 5: Move downloaded files to final output directory
            print("Step 5: Moving downloaded files to final location...")            
            downloaded_files = set()
            for f in Path(temp_modis_dir).rglob('*.hdf'):
                if f.is_file() and f.stat().st_size > 0:
                    downloaded_files.add(f.name)
                    shutil.move(str(f), Path(output_modis_dir) / f.name)
            print(f"Successfully moved {len(downloaded_files)} files to: {output_modis_dir}")

       
        # Step 6: Verify download completeness
        print("Step 6: Verifying download completeness...")
        count = len(list(Path(output_modis_dir).rglob('*.hdf')))
        
        if len(all_urls) <= count:
            print(f"Download successful: expected {len(all_urls)} files, found {count} files")
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
            failed_links = [url for url in all_urls if url.split('/')[-1] not in existing_files]
            
            # Save failed URLs for manual retry
            failed_link_file = f"{temp_dir}Failed_MODIS_{data_product}_urls.txt"
            with open(failed_link_file, "w") as f:
                f.write("\n".join(failed_links))
            
            print(f"Warning: Expected {len(all_urls)} files, but downloaded {count} files")
            print(f'Download incomplete. Check {failed_link_file} for missing files and retry manually')
            return False

    except Exception as e:
        print(f"Error in MODIS download process: {e}")
        return False


def main():
    """
    Standalone execution entry point for MODIS download
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
        
        if data_product == 'MCD12Q1':
            start_date = start_date[0:4]+'0101'
            end_date = end_date[0:4]+'0101'

    except Exception as e:
        print(f"Error reading configuration: {e}")
        return

    # Execute the complete download and processing pipeline
    success = download_modis_data(
        area, 
        data_product,
        start_date, 
        end_date,
        getattr(cfg.credentials.earthdata, 'token', None),
        cfg.paths.download_output + f"/landusetype/", 
        cfg.paths.download_temp, 
        cfg.domains.default.resolution.dx, 
        cfg.domains.default.resolution.dy
    )
    
    if success:
        print("MODIS data processing completed successfully")
    else:
        print("MODIS data processing failed")
        sys.exit(1)  # Exit with error code


if __name__ == "__main__":
    main()
