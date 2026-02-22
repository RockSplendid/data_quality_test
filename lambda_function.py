import json
import boto3
import duckdb
import os
from datetime import datetime

# Initialize S3 client
s3_client = boto3.client('s3')

# Your bucket name - UPDATE THIS VARIABLE
BUCKET_NAME = 'datasourcebucket1109'

def lambda_handler(event, context):
    """
    Triggered by S3 upload. Processes a CSV, applies quality rules,
    writes Parquet, and returns metrics for AI anomaly detection.
    
    Optimized for Lambda's memory constraints.
    """
    print("=== MVP Quality Check Lambda Started ===")
    
    # 1. Get the uploaded CSV file details from the S3 event
    try:
        record = event['Records'][0]
        source_bucket = record['s3']['bucket']['name']
        source_key = record['s3']['object']['key']  # e.g., 'RawZone/online_retail_II.csv'
        file_name = os.path.basename(source_key)
        print(f"Processing file: s3://{source_bucket}/{source_key}")
        
        # Validate it's in the RawZone
        if not source_key.startswith('RawZone/'):
            print(f"File not in RawZone. Ignoring.")
            return {'statusCode': 200, 'body': 'File not in RawZone.'}
            
    except Exception as e:
        print(f"Error parsing S3 event: {e}")
        return {'statusCode': 400, 'body': 'Invalid S3 event.'}
    
    # 2. Download the CSV file from S3 to /tmp (Lambda's writable directory)
    temp_csv = f'/tmp/{file_name}'
    try:
        print(f"Downloading to {temp_csv}...")
        s3_client.download_file(source_bucket, source_key, temp_csv)
        file_size = os.path.getsize(temp_csv)
        print(f"Downloaded CSV, size: {file_size} bytes")
    except Exception as e:
        print(f"Error downloading from S3: {e}")
        return {'statusCode': 500, 'body': 'Failed to download CSV.'}
    
    # 3. Load CSV into DuckDB and perform quality checks
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
        print("Connected to DuckDB")
        
        # Load CSV directly from the file (memory efficient)
        conn.execute(f"""
            CREATE OR REPLACE TABLE raw_data AS 
            SELECT * FROM read_csv_auto('{temp_csv}')
        """)
        
        # Get initial count
        initial_count_result = conn.execute("SELECT COUNT(*) FROM raw_data").fetchone()
        initial_count = initial_count_result[0]
        metrics['initial_record_count'] = initial_count
        print(f"Initial record count: {initial_count}")
        
        # RULE 1: Remove rows where 'CustomerID' is NULL or empty string
        print("Applying Rule 1: CustomerID check...")
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
        print(f"Records after CustomerID check: {count_step1} (removed {metrics['records_removed_customer_id']})")
        
        # RULE 2: Remove rows where 'Price' is not a positive number
        print("Applying Rule 2: Price > 0 check...")
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
        print(f"Records after Price check: {final_count} (removed {metrics['records_removed_price']})")
        
        # 4. Write the cleaned data to Parquet and upload to S3 CleanZone
        if final_count > 0:
            # Define the output path in the CleanZone
            clean_key = source_key.replace('RawZone/', 'CleanZone/')
            clean_key = os.path.splitext(clean_key)[0] + '.parquet'
            
            # Write to temporary Parquet file
            temp_parquet = '/tmp/output.parquet'
            conn.execute(f"""
                COPY cleaned_final TO '{temp_parquet}' (FORMAT PARQUET)
            """)
            print(f"Created Parquet file")
            
            # Upload the Parquet file to S3
            s3_client.upload_file(temp_parquet, BUCKET_NAME, clean_key)
            print(f"Successfully uploaded to: s3://{BUCKET_NAME}/{clean_key}")
            
            # Clean up temp Parquet file to free memory
            os.remove(temp_parquet)
        else:
            print("WARNING: No records passed quality checks. No Parquet file written.")
        
        # Close DuckDB connection
        conn.close()
        
    except Exception as e:
        print(f"Error during DuckDB processing: {e}")
        import traceback
        traceback.print_exc()
        # Clean up temp CSV before returning error
        if os.path.exists(temp_csv):
            os.remove(temp_csv)
        return {'statusCode': 500, 'body': f'Data processing failed: {str(e)}'}
    
    # Clean up temp CSV file to free memory
    if os.path.exists(temp_csv):
        os.remove(temp_csv)
    
    # 5. Calculate processing time and finalize metrics
    process_end = datetime.utcnow()
    metrics['processing_time_sec'] = (process_end - process_start).total_seconds()
    
    print("=== Processing Metrics ===")
    print(json.dumps(metrics, indent=2))
    
    # 6. Write metrics to S3 for the AI anomaly detection Lambda
    metrics_key = f"metrics/{datetime.utcnow().strftime('%Y/%m/%d')}/{file_name}_{process_start.strftime('%H%M%S')}.json"
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=metrics_key,
        Body=json.dumps(metrics, indent=2)
    )
    print(f"Metrics saved: s3://{BUCKET_NAME}/{metrics_key}")
    
    print("=== Lambda Execution Finished Successfully ===")
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Processing complete.',
            'records_processed': final_count,
            'metrics_location': f"s3://{BUCKET_NAME}/{metrics_key}"
        })
    }