import json
import boto3
import duckdb
import os
from datetime import datetime, timezone

# Initialize S3 client
s3_client = boto3.client('s3')

# Configuration
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'datasourcebucket1109')
SOURCE_BUCKET = os.environ.get('SOURCE_BUCKET', BUCKET_NAME)
SOURCE_KEY = os.environ.get('SOURCE_KEY', 'RawZone/online_retail_II.csv')
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')  # ERROR, INFO, or DEBUG

# Rule group toggles (can be controlled via environment variables)
ENABLE_BASIC_CHECKS = os.environ.get('ENABLE_BASIC_CHECKS', 'true').lower() == 'true'
ENABLE_BUSINESS_RULES = os.environ.get('ENABLE_BUSINESS_RULES', 'true').lower() == 'true'
ENABLE_DATA_INTEGRITY = os.environ.get('ENABLE_DATA_INTEGRITY', 'false').lower() == 'true'
ENABLE_OUTLIER_DETECTION = os.environ.get('ENABLE_OUTLIER_DETECTION', 'false').lower() == 'true'
ENABLE_TEMPORAL_CHECKS = os.environ.get('ENABLE_TEMPORAL_CHECKS', 'false').lower() == 'true'
ENABLE_DUPLICATE_DETECTION = os.environ.get('ENABLE_DUPLICATE_DETECTION', 'false').lower() == 'true'
ENABLE_COMPLETENESS_CHECKS = os.environ.get('ENABLE_COMPLETENESS_CHECKS', 'false').lower() == 'true'
ENABLE_SCHEMA_VALIDATION = os.environ.get('ENABLE_SCHEMA_VALIDATION', 'false').lower() == 'true'


def log(message, level='INFO'):
    """Conditional logging based on LOG_LEVEL"""
    levels = {'ERROR': 0, 'INFO': 1, 'DEBUG': 2}
    if levels.get(level, 1) <= levels.get(LOG_LEVEL, 1):
        print(message)


def apply_basic_checks(conn, metrics):
    """
    Basic data type and null checks (MVP rules)
    - Remove rows with null/empty CustomerID
    - Remove rows with Price <= 0
    """
    start_time = datetime.now(timezone.utc)
    
    # Get initial count
    initial_count = conn.execute("SELECT COUNT(*) FROM current_data").fetchone()[0]
    
    rule_metrics = {
        'enabled': True,
        'records_in': initial_count,
        'records_out': 0,
        'records_removed': 0,
        'processing_time_sec': 0.0,
        'rules': {}
    }
    
    # Rule 1: Remove null/empty CustomerID
    conn.execute("""
        CREATE OR REPLACE TABLE current_data AS
        SELECT * 
        FROM current_data
        WHERE "CustomerID" IS NOT NULL 
          AND TRIM(CAST("CustomerID" AS VARCHAR)) != ''
    """)
    count_after_customer = conn.execute("SELECT COUNT(*) FROM current_data").fetchone()[0]
    rule_metrics['rules']['null_customer_id'] = {'removed': initial_count - count_after_customer}
    
    # Rule 2: Remove Price <= 0
    conn.execute("""
        CREATE OR REPLACE TABLE current_data AS
        SELECT * 
        FROM current_data
        WHERE TRY_CAST("Price" AS DOUBLE) > 0
    """)
    count_after_price = conn.execute("SELECT COUNT(*) FROM current_data").fetchone()[0]
    rule_metrics['rules']['invalid_price'] = {'removed': count_after_customer - count_after_price}
    
    # Finalize metrics
    rule_metrics['records_out'] = count_after_price
    rule_metrics['records_removed'] = initial_count - count_after_price
    rule_metrics['processing_time_sec'] = (datetime.now(timezone.utc) - start_time).total_seconds()
    
    log(f"Basic checks: {initial_count} → {count_after_price} ({rule_metrics['records_removed']} removed)", 'DEBUG')
    
    return rule_metrics


def apply_business_rules(conn, metrics):
    """
    Business logic validation rules
    - Cancellation invoices (Invoice starts with 'C') must have negative quantities
    - Regular invoices must have positive quantities
    - No zero quantities allowed
    """
    start_time = datetime.now(timezone.utc)
    
    # Get initial count
    initial_count = conn.execute("SELECT COUNT(*) FROM current_data").fetchone()[0]
    
    rule_metrics = {
        'enabled': True,
        'records_in': initial_count,
        'records_out': 0,
        'records_removed': 0,
        'processing_time_sec': 0.0,
        'rules': {}
    }
    
    # Rule 1: Cancellation invoices must have negative quantities
    conn.execute("""
        CREATE OR REPLACE TABLE current_data AS
        SELECT * 
        FROM current_data
        WHERE NOT (
            SUBSTRING(CAST("Invoice" AS VARCHAR), 1, 1) = 'C' 
            AND "Quantity" > 0
        )
    """)
    count_after_cancel = conn.execute("SELECT COUNT(*) FROM current_data").fetchone()[0]
    rule_metrics['rules']['cancellation_positive_qty'] = {'removed': initial_count - count_after_cancel}
    
    # Rule 2: Regular invoices must have positive quantities
    conn.execute("""
        CREATE OR REPLACE TABLE current_data AS
        SELECT * 
        FROM current_data
        WHERE NOT (
            SUBSTRING(CAST("Invoice" AS VARCHAR), 1, 1) != 'C' 
            AND "Quantity" < 0
        )
    """)
    count_after_regular = conn.execute("SELECT COUNT(*) FROM current_data").fetchone()[0]
    rule_metrics['rules']['regular_negative_qty'] = {'removed': count_after_cancel - count_after_regular}
    
    # Rule 3: No zero quantities
    conn.execute("""
        CREATE OR REPLACE TABLE current_data AS
        SELECT * 
        FROM current_data
        WHERE "Quantity" != 0
    """)
    count_after_zero = conn.execute("SELECT COUNT(*) FROM current_data").fetchone()[0]
    rule_metrics['rules']['zero_quantity'] = {'removed': count_after_regular - count_after_zero}
    
    # Finalize metrics
    rule_metrics['records_out'] = count_after_zero
    rule_metrics['records_removed'] = initial_count - count_after_zero
    rule_metrics['processing_time_sec'] = (datetime.now(timezone.utc) - start_time).total_seconds()
    
    log(f"Business rules: {initial_count} → {count_after_zero} ({rule_metrics['records_removed']} removed)", 'DEBUG')
    
    return rule_metrics


def apply_data_integrity_checks(conn, metrics):
    """
    Data integrity validation rules
    - Missing CustomerID when Country exists (referential integrity)
    - Same Invoice must have consistent InvoiceDate
    - Same Invoice must have same CustomerID
    """
    start_time = datetime.now(timezone.utc)
    
    initial_count = conn.execute("SELECT COUNT(*) FROM current_data").fetchone()[0]
    
    rule_metrics = {
        'enabled': True,
        'records_in': initial_count,
        'records_out': 0,
        'records_removed': 0,
        'processing_time_sec': 0.0,
        'rules': {}
    }
    
    # Rule 1: If Country exists, CustomerID should exist (referential integrity)
    conn.execute("""
        CREATE OR REPLACE TABLE current_data AS
        SELECT * 
        FROM current_data
        WHERE NOT ("Country" IS NOT NULL AND "CustomerID" IS NULL)
    """)
    count_after_ref = conn.execute("SELECT COUNT(*) FROM current_data").fetchone()[0]
    rule_metrics['rules']['missing_customer_with_country'] = {'removed': initial_count - count_after_ref}
    
    # Rule 2: Same Invoice must have consistent InvoiceDate
    # Create a temp table with invoice-level date consistency check
    conn.execute("""
        CREATE OR REPLACE TABLE invoice_date_check AS
        SELECT "Invoice", COUNT(DISTINCT "InvoiceDate") as date_count
        FROM current_data
        GROUP BY "Invoice"
        HAVING COUNT(DISTINCT "InvoiceDate") > 1
    """)
    
    conn.execute("""
        CREATE OR REPLACE TABLE current_data AS
        SELECT c.* 
        FROM current_data c
        LEFT JOIN invoice_date_check idc ON c."Invoice" = idc."Invoice"
        WHERE idc."Invoice" IS NULL
    """)
    count_after_date = conn.execute("SELECT COUNT(*) FROM current_data").fetchone()[0]
    rule_metrics['rules']['inconsistent_invoice_dates'] = {'removed': count_after_ref - count_after_date}
    
    # Rule 3: Same Invoice must have same CustomerID
    conn.execute("""
        CREATE OR REPLACE TABLE invoice_customer_check AS
        SELECT "Invoice", COUNT(DISTINCT "CustomerID") as customer_count
        FROM current_data
        WHERE "CustomerID" IS NOT NULL
        GROUP BY "Invoice"
        HAVING COUNT(DISTINCT "CustomerID") > 1
    """)
    
    conn.execute("""
        CREATE OR REPLACE TABLE current_data AS
        SELECT c.* 
        FROM current_data c
        LEFT JOIN invoice_customer_check icc ON c."Invoice" = icc."Invoice"
        WHERE icc."Invoice" IS NULL
    """)
    count_after_customer = conn.execute("SELECT COUNT(*) FROM current_data").fetchone()[0]
    rule_metrics['rules']['inconsistent_invoice_customers'] = {'removed': count_after_date - count_after_customer}
    
    # Cleanup temp tables
    conn.execute("DROP TABLE IF EXISTS invoice_date_check")
    conn.execute("DROP TABLE IF EXISTS invoice_customer_check")
    
    rule_metrics['records_out'] = count_after_customer
    rule_metrics['records_removed'] = initial_count - count_after_customer
    rule_metrics['processing_time_sec'] = (datetime.now(timezone.utc) - start_time).total_seconds()
    
    log(f"Data integrity: {initial_count} → {count_after_customer} ({rule_metrics['records_removed']} removed)", 'DEBUG')
    
    return rule_metrics


def process_s3_object(source_bucket, source_key):
    """
    Main processing entry for local testing (same S3 flow as Lambda)
    """
    log("=== Data Quality Lambda Started ===", 'INFO')
    
    # Parse source details
    try:
        file_name = os.path.basename(source_key)
        
        # Determine if this is anomalous data based on prefix
        is_anomalous = source_key.startswith('RawZone-Anomalies/')
        data_type = 'anomalies' if is_anomalous else 'clean'
        
        log(f"File: s3://{source_bucket}/{source_key} (Type: {data_type})", 'INFO')
        
        # Validate prefix
        if not (source_key.startswith('RawZone/') or source_key.startswith('RawZone-Anomalies/')):
            log(f"File not in valid prefix. Ignoring.", 'INFO')
            return {'statusCode': 200, 'body': 'File not in valid prefix.'}
            
    except Exception as e:
        log(f"Error parsing S3 event: {e}", 'ERROR')
        return {'statusCode': 400, 'body': 'Invalid source inputs.'}
    
    # Download CSV to /tmp
    temp_csv = f'/tmp/{file_name}'
    try:
        s3_client.download_file(source_bucket, source_key, temp_csv)
        log(f"Downloaded: {os.path.getsize(temp_csv)} bytes", 'DEBUG')
    except Exception as e:
        log(f"Error downloading from S3: {e}", 'ERROR')
        return {'statusCode': 500, 'body': 'Failed to download CSV.'}
    
    # Initialize metrics
    process_start = datetime.now(timezone.utc)
    metrics = {
        'timestamp': process_start.isoformat(),
        'source_file': source_key,
        'data_type': data_type,
        'initial_record_count': 0,
        'final_record_count': 0,
        'total_records_removed': 0,
        'removal_percentage': 0.0,
        'processing_time_total_sec': 0.0,
        'rule_groups': {}
    }
    
    try:
        # Connect to DuckDB
        conn = duckdb.connect(database=':memory:')
        
        # Load CSV
        conn.execute(f"""
            CREATE OR REPLACE TABLE current_data AS 
            SELECT * FROM read_csv_auto('{temp_csv}')
        """)
        
        initial_count = conn.execute("SELECT COUNT(*) FROM current_data").fetchone()[0]
        metrics['initial_record_count'] = initial_count
        log(f"Initial records: {initial_count}", 'INFO')
        
        # Apply rule groups based on configuration
        if ENABLE_BASIC_CHECKS:
            metrics['rule_groups']['basic_checks'] = apply_basic_checks(conn, metrics)
        
        if ENABLE_BUSINESS_RULES:
            metrics['rule_groups']['business_rules'] = apply_business_rules(conn, metrics)
        
        if ENABLE_DATA_INTEGRITY:
            metrics['rule_groups']['data_integrity'] = apply_data_integrity_checks(conn, metrics)
        
        # Future rule groups will be added here
        # if ENABLE_OUTLIER_DETECTION:
        #     metrics['rule_groups']['outlier_detection'] = apply_outlier_detection(conn, metrics)
        
        # Get final count
        final_count = conn.execute("SELECT COUNT(*) FROM current_data").fetchone()[0]
        metrics['final_record_count'] = final_count
        metrics['total_records_removed'] = initial_count - final_count
        metrics['removal_percentage'] = round((metrics['total_records_removed'] / initial_count * 100), 2) if initial_count > 0 else 0.0
        
        log(f"Final records: {final_count} (Removed: {metrics['total_records_removed']}, {metrics['removal_percentage']}%)", 'INFO')
        
        # Write Parquet to appropriate CleanZone
        if final_count > 0:
            # Determine output prefix based on input prefix
            if is_anomalous:
                clean_key = source_key.replace('RawZone-Anomalies/', 'CleanZone-Anomalies/')
            else:
                clean_key = source_key.replace('RawZone/', 'CleanZone/')
            
            clean_key = os.path.splitext(clean_key)[0] + '.parquet'
            
            # Write to temp Parquet
            temp_parquet = '/tmp/output.parquet'
            conn.execute(f"COPY current_data TO '{temp_parquet}' (FORMAT PARQUET)")
            
            # Upload to S3
            s3_client.upload_file(temp_parquet, BUCKET_NAME, clean_key)
            log(f"Parquet uploaded: s3://{BUCKET_NAME}/{clean_key}", 'DEBUG')
            
            # Cleanup temp files
            os.remove(temp_parquet)
        else:
            log("No records passed quality checks. No Parquet written.", 'INFO')
        
        conn.close()
        
    except Exception as e:
        log(f"Error during processing: {e}", 'ERROR')
        import traceback
        log(traceback.format_exc(), 'ERROR')
        if os.path.exists(temp_csv):
            os.remove(temp_csv)
        return {'statusCode': 500, 'body': f'Processing failed: {str(e)}'}
    
    # Cleanup temp CSV
    if os.path.exists(temp_csv):
        os.remove(temp_csv)
    
    # Finalize metrics
    metrics['processing_time_total_sec'] = (datetime.now(timezone.utc) - process_start).total_seconds()
    
    # Save metrics to appropriate path
    metrics_key = f"metrics/{data_type}/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/{file_name}_{process_start.strftime('%H%M%S')}.json"
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=metrics_key,
        Body=json.dumps(metrics, indent=2)
    )
    log(f"Metrics saved: s3://{BUCKET_NAME}/{metrics_key}", 'DEBUG')
    
    log("=== Lambda Execution Complete ===", 'INFO')
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Processing complete.',
            'data_type': data_type,
            'records_processed': final_count,
            'records_removed': metrics['total_records_removed'],
            'removal_percentage': metrics['removal_percentage'],
            'metrics_location': f"s3://{BUCKET_NAME}/{metrics_key}"
        })
    }


def main():
    if not SOURCE_KEY:
        print(json.dumps({
            'statusCode': 400,
            'body': 'Missing required env var: SOURCE_KEY'
        }, indent=2))
        return 1

    response = process_s3_object(SOURCE_BUCKET, SOURCE_KEY)
    print(json.dumps(response, indent=2))
    return 0 if response.get('statusCode') == 200 else 1


if __name__ == '__main__':
    raise SystemExit(main())