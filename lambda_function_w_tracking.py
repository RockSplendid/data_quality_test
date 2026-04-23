import json
import boto3
import duckdb
import os
from datetime import datetime

# Initialize S3 client
s3_client = boto3.client('s3')

# Configuration
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'datasourcebucket1109')
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')  # ERROR, INFO, or DEBUG

# Rule group enable/disable flags
ENABLE_BASIC_CHECKS = os.environ.get('ENABLE_BASIC_CHECKS', 'true').lower() == 'true'
ENABLE_BUSINESS_RULES = os.environ.get('ENABLE_BUSINESS_RULES', 'true').lower() == 'true'


def log(message, level='INFO'):
    """Conditional logging"""
    levels = {'ERROR': 0, 'INFO': 1, 'DEBUG': 2}
    if levels.get(level, 1) <= levels.get(LOG_LEVEL, 1):
        print(message)


def apply_basic_checks(conn, table_name='raw_data'):
    """
    PHASE 0: Basic Checks
    Returns metrics + list of flagged row IDs
    """
    start_time = datetime.utcnow()
    
    count_before = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    
    rule_metrics = {}
    all_flagged_ids = []
    
    # DATA CLEANING: Trim and standardize string fields
    log("Cleaning string fields...", 'DEBUG')
    conn.execute(f"""
        UPDATE {table_name}
        SET 
            "StockCode" = TRIM(UPPER(CAST("StockCode" AS VARCHAR))),
            "Description" = TRIM(CAST("Description" AS VARCHAR)),
            "Invoice" = TRIM(UPPER(CAST("Invoice" AS VARCHAR)))
    """)
    
    # NOTE: NULL CustomerID check REMOVED
    # Reason: NULL CustomerID rows are legitimate operational entries (postage, adjustments, etc.)
    # Business rules will catch actual violations (e.g., negative qty without cancellation)
    
    # Get flagged row IDs for invalid Price
    # Flag: Price is null, OR (Price < 0 AND NOT a bank adjustment)
    flagged_price = conn.execute(f"""
        SELECT "__row_id" FROM {table_name}
        WHERE NOT (
            TRY_CAST("Price" AS DOUBLE) > 0
            OR TRY_CAST("Price" AS DOUBLE) = 0
            OR (
                TRY_CAST("Price" AS DOUBLE) < 0
                AND "StockCode" = 'B'
                AND SUBSTRING("Invoice", 1, 1) = 'A'
            )
        )
    """).fetchall()
    flagged_price_ids = [int(row[0]) for row in flagged_price]
    all_flagged_ids.extend(flagged_price_ids)
    
    # Rule: Valid Price (positive, zero, or negative bank adjustments only)
    conn.execute(f"""
        CREATE OR REPLACE TABLE temp_basic_final AS
        SELECT * FROM {table_name}
        WHERE 
            TRY_CAST("Price" AS DOUBLE) > 0
            OR TRY_CAST("Price" AS DOUBLE) = 0
            OR (
                TRY_CAST("Price" AS DOUBLE) < 0
                AND "StockCode" = 'B'
                AND SUBSTRING("Invoice", 1, 1) = 'A'
            )
    """)
    count_after_price = conn.execute("SELECT COUNT(*) FROM temp_basic_final").fetchone()[0]
    rule_metrics['invalid_price'] = {
        'removed': count_before - count_after_price,
        'flagged_ids': flagged_price_ids,
        'description': 'Removed rows with invalid prices (null, or negative non-bank-adjustments)'
    }
    
    # Replace original table
    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    conn.execute(f"ALTER TABLE temp_basic_final RENAME TO {table_name}")
    
    processing_time = (datetime.utcnow() - start_time).total_seconds()
    
    return {
        'enabled': True,
        'records_in': count_before,
        'records_out': count_after_price,
        'records_removed': count_before - count_after_price,
        'processing_time_sec': processing_time,
        'rules': rule_metrics,
        'flagged_row_ids': list(set(all_flagged_ids))
    }


def apply_business_rules(conn, table_name='raw_data'):
    """
    PHASE 1: Business Rules
    Returns metrics + list of flagged row IDs
    """
    start_time = datetime.utcnow()
    
    count_before = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    
    rule_metrics = {}
    all_flagged_ids = []
    
    # Get flagged row IDs for cancellation with positive qty
    flagged_cancel = conn.execute(f"""
        SELECT "__row_id" FROM {table_name}
        WHERE SUBSTRING(CAST("Invoice" AS VARCHAR), 1, 1) = 'C' 
          AND "Quantity" > 0
    """).fetchall()
    flagged_cancel_ids = [int(row[0]) for row in flagged_cancel]
    all_flagged_ids.extend(flagged_cancel_ids)
    
    # Rule 1: Cancellations must have negative quantity
    conn.execute(f"""
        CREATE OR REPLACE TABLE temp_biz_1 AS
        SELECT * FROM {table_name}
        WHERE NOT (
            SUBSTRING(CAST("Invoice" AS VARCHAR), 1, 1) = 'C' 
            AND "Quantity" > 0
        )
    """)
    count_after_cancel = conn.execute("SELECT COUNT(*) FROM temp_biz_1").fetchone()[0]
    rule_metrics['cancellation_positive_qty'] = {
        'removed': count_before - count_after_cancel,
        'flagged_ids': flagged_cancel_ids
    }
    
    # Get flagged row IDs for regular with negative qty
    flagged_regular = conn.execute("""
        SELECT "__row_id" FROM temp_biz_1
        WHERE SUBSTRING(CAST("Invoice" AS VARCHAR), 1, 1) != 'C' 
          AND "Quantity" < 0
    """).fetchall()
    flagged_regular_ids = [int(row[0]) for row in flagged_regular]
    all_flagged_ids.extend(flagged_regular_ids)
    
    # Rule 2: Regular invoices must have positive quantity
    conn.execute("""
        CREATE OR REPLACE TABLE temp_biz_2 AS
        SELECT * FROM temp_biz_1
        WHERE NOT (
            SUBSTRING(CAST("Invoice" AS VARCHAR), 1, 1) != 'C' 
            AND "Quantity" < 0
        )
    """)
    count_after_regular = conn.execute("SELECT COUNT(*) FROM temp_biz_2").fetchone()[0]
    rule_metrics['regular_negative_qty'] = {
        'removed': count_after_cancel - count_after_regular,
        'flagged_ids': flagged_regular_ids
    }
    
    # Get flagged row IDs for zero quantity
    flagged_zero = conn.execute("""
        SELECT "__row_id" FROM temp_biz_2
        WHERE "Quantity" = 0
    """).fetchall()
    flagged_zero_ids = [int(row[0]) for row in flagged_zero]
    all_flagged_ids.extend(flagged_zero_ids)
    
    # Rule 3: No zero quantities
    conn.execute("""
        CREATE OR REPLACE TABLE temp_biz_final AS
        SELECT * FROM temp_biz_2
        WHERE "Quantity" != 0
    """)
    count_after_zero = conn.execute("SELECT COUNT(*) FROM temp_biz_final").fetchone()[0]
    rule_metrics['zero_quantity'] = {
        'removed': count_after_regular - count_after_zero,
        'flagged_ids': flagged_zero_ids
    }
    
    # Replace original table
    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    conn.execute(f"ALTER TABLE temp_biz_final RENAME TO {table_name}")
    conn.execute("DROP TABLE IF EXISTS temp_biz_1")
    conn.execute("DROP TABLE IF EXISTS temp_biz_2")
    
    processing_time = (datetime.utcnow() - start_time).total_seconds()
    
    return {
        'enabled': True,
        'records_in': count_before,
        'records_out': count_after_zero,
        'records_removed': count_before - count_after_zero,
        'processing_time_sec': processing_time,
        'rules': rule_metrics,
        'flagged_row_ids': list(set(all_flagged_ids))
    }


def lambda_handler(event, context):
    """
    Modular data quality pipeline with flagged row tracking
    for Precision/Recall/F1 evaluation
    """
    log("=== Data Quality Pipeline Started ===", 'INFO')
    
    # Parse S3 event
    try:
        record = event['Records'][0]
        source_bucket = record['s3']['bucket']['name']
        source_key = record['s3']['object']['key']
        file_name = os.path.basename(source_key)
        
        log(f"Processing: s3://{source_bucket}/{source_key}", 'INFO')
        
        is_anomalous = 'Anomalies' in source_key or 'anomalies' in source_key
        data_type = 'anomalies' if is_anomalous else 'clean'
        
        if not (source_key.startswith('RawZone/') or source_key.startswith('RawZone-Anomalies/')):
            log(f"File not in valid RawZone prefix", 'INFO')
            return {'statusCode': 200, 'body': 'File not in valid RawZone prefix.'}
            
    except Exception as e:
        log(f"ERROR parsing S3 event: {e}", 'ERROR')
        return {'statusCode': 400, 'body': 'Invalid S3 event.'}
    
    # Download CSV
    temp_csv = f'/tmp/{file_name}'
    try:
        log(f"Downloading file...", 'DEBUG')
        s3_client.download_file(source_bucket, source_key, temp_csv)
        log(f"Downloaded: {os.path.getsize(temp_csv)} bytes", 'DEBUG')
    except Exception as e:
        log(f"ERROR downloading: {e}", 'ERROR')
        return {'statusCode': 500, 'body': 'Failed to download CSV.'}
    
    # Initialize metrics
    metrics = {
        'timestamp': datetime.utcnow().isoformat(),
        'source_file': source_key,
        'data_type': data_type,
        'initial_record_count': 0,
        'final_record_count': 0,
        'total_records_removed': 0,
        'removal_percentage': 0.0,
        'processing_time_total_sec': 0.0,
        'rule_groups': {},
        'all_flagged_row_ids': []  # NEW: Track all flagged rows
    }
    
    process_start = datetime.utcnow()
    
    try:
        conn = duckdb.connect(database=':memory:')
        log("DuckDB connected", 'DEBUG')
        
        # Load CSV and add row ID column
        conn.execute(f"""
            CREATE TABLE raw_data AS 
            SELECT *, ROW_NUMBER() OVER () - 1 AS "__row_id"
            FROM read_csv_auto('{temp_csv}')
        """)
        
        initial_count = conn.execute("SELECT COUNT(*) FROM raw_data").fetchone()[0]
        metrics['initial_record_count'] = initial_count
        log(f"Loaded {initial_count:,} records", 'INFO')
        
        # Apply rule groups
        current_table = 'raw_data'
        
        # PHASE 0: Basic Checks
        if ENABLE_BASIC_CHECKS:
            log("Applying basic checks...", 'DEBUG')
            basic_result = apply_basic_checks(conn, current_table)
            metrics['rule_groups']['basic_checks'] = basic_result
            metrics['all_flagged_row_ids'].extend(basic_result['flagged_row_ids'])
        else:
            metrics['rule_groups']['basic_checks'] = {'enabled': False}
        
        # PHASE 1: Business Rules
        if ENABLE_BUSINESS_RULES:
            log("Applying business rules...", 'DEBUG')
            business_result = apply_business_rules(conn, current_table)
            metrics['rule_groups']['business_rules'] = business_result
            metrics['all_flagged_row_ids'].extend(business_result['flagged_row_ids'])
        else:
            metrics['rule_groups']['business_rules'] = {'enabled': False}
        
        # Deduplicate flagged IDs
        metrics['all_flagged_row_ids'] = sorted(list(set(metrics['all_flagged_row_ids'])))
        
        # Get final count
        final_count = conn.execute(f"SELECT COUNT(*) FROM {current_table}").fetchone()[0]
        metrics['final_record_count'] = final_count
        metrics['total_records_removed'] = initial_count - final_count
        metrics['removal_percentage'] = round(
            (metrics['total_records_removed'] / initial_count * 100) if initial_count > 0 else 0, 
            2
        )
        
        log(f"Removed {metrics['total_records_removed']:,} records ({metrics['removal_percentage']}%)", 'INFO')
        
        # Write Parquet
        if final_count > 0:
            if is_anomalous:
                clean_key = source_key.replace('RawZone-Anomalies/', 'CleanZone-RulesBased-Anomalies/')
            else:
                clean_key = source_key.replace('RawZone/', 'CleanZone-RulesBased/')
            clean_key = os.path.splitext(clean_key)[0] + '.parquet'
            
            temp_parquet = '/tmp/output.parquet'
            # Remove __row_id before saving
            conn.execute(f"""
                CREATE TABLE final_output AS
                SELECT * FROM {current_table}
            """)
            conn.execute(f"COPY final_output TO '{temp_parquet}' (FORMAT PARQUET)")
            
            s3_client.upload_file(temp_parquet, BUCKET_NAME, clean_key)
            log(f"Uploaded: s3://{BUCKET_NAME}/{clean_key}", 'DEBUG')
            
            os.remove(temp_parquet)
        else:
            log("WARNING: No records passed quality checks", 'INFO')
        
        conn.close()
        
    except Exception as e:
        log(f"ERROR during processing: {e}", 'ERROR')
        import traceback
        traceback.print_exc()
        if os.path.exists(temp_csv):
            os.remove(temp_csv)
        return {'statusCode': 500, 'body': f'Processing failed: {str(e)}'}
    
    # Cleanup
    if os.path.exists(temp_csv):
        os.remove(temp_csv)
    
    # Finalize metrics
    process_end = datetime.utcnow()
    metrics['processing_time_total_sec'] = round((process_end - process_start).total_seconds(), 3)
    
    # Save metrics to S3
    metrics_key = f"metrics/{data_type}/{datetime.utcnow().strftime('%Y/%m/%d')}/{file_name}_{process_start.strftime('%H%M%S')}.json"
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=metrics_key,
        Body=json.dumps(metrics, indent=2)
    )
    
    log(f"Metrics saved: s3://{BUCKET_NAME}/{metrics_key}", 'DEBUG')
    log("=== Pipeline Complete ===", 'INFO')
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Processing complete',
            'data_type': data_type,
            'records_processed': final_count,
            'records_removed': metrics['total_records_removed'],
            'removal_percentage': metrics['removal_percentage'],
            'metrics_location': f"s3://{BUCKET_NAME}/{metrics_key}"
        })
    }