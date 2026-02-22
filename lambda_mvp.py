import json
import boto3
import duckdb
import os
import sys
from datetime import datetime

# Initialize S3 client
s3_client = boto3.client('s3')

# Your bucket name
BUCKET_NAME = 'datasourcebucket1109'

def process_csv_file(source_key, verbose=True):
    """
    Local version: Processes a CSV from S3, applies quality rules,
    writes Parquet, and returns metrics for AI anomaly detection.
    
    Args:
        source_key: S3 key path like 'RawZone/online_retail_II.csv'
        verbose: If False, suppresses detailed output
    """
    def log(msg):
        if verbose:
            print(msg)
    
    log("=== MVP Quality Check Started ===")
    
    source_bucket = BUCKET_NAME
    file_name = os.path.basename(source_key)
    log(f"Processing file: s3://{source_bucket}/{source_key}")
    
    # Validate it's in the RawZone
    if not source_key.startswith('RawZone/'):
        log(f"File not in RawZone. Ignoring.")
        return {'statusCode': 200, 'body': 'File not in RawZone.'}
    
    # SECTION 1: Download the CSV file from S3 into memory
    log("\n--- SECTION 1: Downloading CSV from S3 ---")
    try:
        response = s3_client.get_object(Bucket=source_bucket, Key=source_key)
        csv_content = response['Body'].read().decode('utf-8')
        log(f"✓ Downloaded CSV successfully")
        log(f"  Size: {len(csv_content)} characters")
        log(f"  First 200 chars: {csv_content[:200]}")
    except Exception as e:
        log(f"✗ Error downloading from S3: {e}")
        return {'statusCode': 500, 'body': 'Failed to download CSV.'}
    
    # SECTION 2: Load CSV into DuckDB and perform quality checks
    log("\n--- SECTION 2: Loading into DuckDB ---")
    
    # METRICS DICTIONARY - This is the key output for the AI layer
    metrics = {
        'timestamp': datetime.utcnow().isoformat(),
        'source_file': source_key,
        'initial_record_count': 0,
        'after_customer_id_check': 0,
        'after_price_check': 0,
        'records_removed_customer_id': 0,
        'records_removed_price': 0,
        'processing_time_sec': 0
    }
    
    process_start = datetime.utcnow()
    
    try:
        # Connect to an in-memory DuckDB database
        conn = duckdb.connect(database=':memory:')
        log("✓ Connected to DuckDB")
        
        # Save CSV to a temporary file (DuckDB needs a file path or string content)
        temp_csv = '/tmp/temp_input.csv'
        with open(temp_csv, 'w', encoding='utf-8') as f:
            f.write(csv_content)
        
        # Load CSV from the temporary file
        log("  Loading CSV data...")
        conn.execute(f"""
            CREATE OR REPLACE TABLE raw_data AS 
            SELECT * FROM read_csv_auto('{temp_csv}')
        """)
        
        # Get initial count
        initial_count_result = conn.execute("SELECT COUNT(*) FROM raw_data").fetchone()
        initial_count = initial_count_result[0]
        metrics['initial_record_count'] = initial_count
        log(f"✓ Loaded CSV into DuckDB")
        log(f"  Initial record count: {initial_count}")
        
        # Show column names
        columns = conn.execute("PRAGMA table_info(raw_data)").fetchall()
        column_names = [col[1] for col in columns]
        log(f"  Columns found: {column_names}")
        
        # SECTION 3: Apply Quality Rules
        log("\n--- SECTION 3: Applying Quality Rules ---")
        
        # RULE 1: Remove rows where 'CustomerID' is NULL or empty string
        log("Rule 1: Checking CustomerID...")
        conn.execute("""
            CREATE OR REPLACE TABLE cleaned_step1 AS
            SELECT * 
            FROM raw_data 
            WHERE "CustomerID" IS NOT NULL 
              AND TRIM(CAST("CustomerID" AS VARCHAR)) != ''
        """)
        count_step1_result = conn.execute("SELECT COUNT(*) FROM cleaned_step1").fetchone()
        count_step1 = count_step1_result[0]
        metrics['after_customer_id_check'] = count_step1
        metrics['records_removed_customer_id'] = initial_count - count_step1
        log(f"✓ Records after CustomerID check: {count_step1}")
        log(f"  Removed: {metrics['records_removed_customer_id']} records")
        
        # RULE 2: Remove rows where 'Price' is not a positive number
        log("\nRule 2: Checking Price > 0...")
        conn.execute("""
            CREATE OR REPLACE TABLE cleaned_final AS
            SELECT *,
                   CAST("Price" AS DOUBLE) AS Price_numeric
            FROM cleaned_step1 
            WHERE TRY_CAST("Price" AS DOUBLE) > 0
        """)
        final_count_result = conn.execute("SELECT COUNT(*) FROM cleaned_final").fetchone()
        final_count = final_count_result[0]
        metrics['after_price_check'] = final_count
        metrics['records_removed_price'] = count_step1 - final_count
        log(f"✓ Records after Price > 0 check: {final_count}")
        log(f"  Removed: {metrics['records_removed_price']} records")
        
        # Show a sample of cleaned data (optional - just first 5 rows)
        if verbose:
            log("\nSample of cleaned data (first 5 rows):")
            sample = conn.execute("SELECT * FROM cleaned_final LIMIT 5").fetchall()
            for i, row in enumerate(sample, 1):
                log(f"  Row {i}: {row[:5]}...")  # Show first 5 columns only
        
        # SECTION 4: Write Parquet to S3 CleanZone
        log("\n--- SECTION 4: Writing Parquet to S3 ---")
        if final_count > 0:
            # Write to a temporary local file first (easier for debugging)
            temp_parquet = '/tmp/temp_output.parquet'
            conn.execute(f"""
                COPY cleaned_final TO '{temp_parquet}' (FORMAT PARQUET)
            """)
            log(f"✓ Created temporary Parquet file locally")
            
            # Define the output path in the CleanZone
            clean_key = source_key.replace('RawZone/', 'CleanZone/')
            clean_key = os.path.splitext(clean_key)[0] + '.parquet'
            
            # Upload to S3
            with open(temp_parquet, 'rb') as f:
                s3_client.put_object(
                    Bucket=BUCKET_NAME,
                    Key=clean_key,
                    Body=f.read()
                )
            log(f"✓ Successfully uploaded Parquet to: s3://{BUCKET_NAME}/{clean_key}")
            
            # Clean up temp file
            os.remove(temp_parquet)
        else:
            log("⚠ WARNING: No records passed quality checks. No Parquet file written.")
        
        # Clean up temporary CSV file
        if os.path.exists('/tmp/temp_input.csv'):
            os.remove('/tmp/temp_input.csv')
        
        conn.close()
        
    except Exception as e:
        log(f"✗ Error during DuckDB processing: {e}")
        import traceback
        traceback.print_exc()
        return {'statusCode': 500, 'body': f'Data processing failed: {str(e)}'}
    
    # SECTION 5: Calculate metrics and save
    log("\n--- SECTION 5: Finalizing Metrics ---")
    process_end = datetime.utcnow()
    metrics['processing_time_sec'] = (process_end - process_start).total_seconds()
    
    log("=== Processing Metrics ===")
    log(json.dumps(metrics, indent=2))
    
    # Write metrics to S3
    metrics_key = f"metrics/{datetime.utcnow().strftime('%Y/%m/%d')}/{file_name}_{process_start.strftime('%H%M%S')}.json"
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=metrics_key,
        Body=json.dumps(metrics, indent=2)
    )
    log(f"✓ Metrics saved for AI analysis: s3://{BUCKET_NAME}/{metrics_key}")
    
    log("\n=== Processing Finished Successfully ===")
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Processing complete.',
            'records_processed': final_count,
            'metrics_location': f"s3://{BUCKET_NAME}/{metrics_key}"
        })
    }


def list_files_in_rawzone():
    """Helper function to list all CSV files in the RawZone"""
    print("Listing files in RawZone...")
    try:
        response = s3_client.list_objects_v2(
            Bucket=BUCKET_NAME,
            Prefix='RawZone/'
        )
        
        if 'Contents' in response:
            print("\nFiles found:")
            for obj in response['Contents']:
                print(f"  - {obj['Key']} ({obj['Size']} bytes)")
            return [obj['Key'] for obj in response['Contents']]
        else:
            print("No files found in RawZone/")
            return []
    except Exception as e:
        print(f"Error listing files: {e}")
        return []


if __name__ == '__main__':
    print("=" * 60)
    print("LOCAL CSV PROCESSOR - DEBUG MODE")
    print("=" * 60)
    
    # Test AWS connection first
    print("\n1. Testing AWS S3 Connection...")
    try:
        response = s3_client.head_bucket(Bucket=BUCKET_NAME)
        print(f"✓ Successfully connected to bucket: {BUCKET_NAME}")
    except Exception as e:
        print(f"✗ Error connecting to S3: {e}")
        print("\nPlease check:")
        print("  1. Run 'aws configure' and enter your credentials")
        print("  2. Ensure your bucket name is correct")
        print("  3. Ensure your AWS region is correct")
        exit(1)
    
    # List available files
    print("\n2. Checking available files...")
    available_files = list_files_in_rawzone()
    
    # Process a specific file
    print("\n3. Processing file...")
    
    # CHANGE THIS to match your actual file in S3
    test_file = 'RawZone/online_retail_II.csv'
    
    # Or uncomment to process the first available file
    # if available_files:
    #     test_file = available_files[0]
    
    print(f"\nProcessing: {test_file}")
    print("-" * 60)
    
    # Set verbose=True to see details, False for minimal output
    result = process_csv_file(test_file, verbose=True)
    
    print("\n" + "=" * 60)
    print("FINAL RESULT:")
    print(json.dumps(result, indent=2))
    print("=" * 60)