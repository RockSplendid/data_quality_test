import json
import boto3
import pickle
import pandas as pd
import numpy as np
import os
from datetime import datetime
from io import BytesIO

# Initialize S3 client
s3_client = boto3.client('s3')

# Configuration
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'datasourcebucket1109')
MODEL_S3_KEY = 'models/isolation_forest_model.pkl'
METADATA_S3_KEY = 'models/feature_metadata.json'
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

# Global variables for model caching (Lambda container reuse)
MODEL = None
FEATURE_METADATA = None


def log(message, level='INFO'):
    """Conditional logging"""
    levels = {'ERROR': 0, 'INFO': 1, 'DEBUG': 2}
    if levels.get(level, 1) <= levels.get(LOG_LEVEL, 1):
        print(message)


def load_model_from_s3():
    """Load model and metadata from S3 (with caching)"""
    global MODEL, FEATURE_METADATA
    
    if MODEL is not None and FEATURE_METADATA is not None:
        log("Using cached model", 'DEBUG')
        return MODEL, FEATURE_METADATA
    
    log("Loading model from S3...", 'DEBUG')
    
    try:
        # Load model
        model_obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=MODEL_S3_KEY)
        MODEL = pickle.loads(model_obj['Body'].read())
        log(f"Model loaded from s3://{BUCKET_NAME}/{MODEL_S3_KEY}", 'DEBUG')
        
        # Load metadata
        metadata_obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=METADATA_S3_KEY)
        FEATURE_METADATA = json.loads(metadata_obj['Body'].read().decode('utf-8'))
        log(f"Metadata loaded from s3://{BUCKET_NAME}/{METADATA_S3_KEY}", 'DEBUG')
        
        return MODEL, FEATURE_METADATA
        
    except Exception as e:
        log(f"ERROR loading model: {e}", 'ERROR')
        raise


def engineer_features(df, metadata):
    """
    Feature engineering for inference (same as training)
    
    Args:
        df: Input dataframe
        metadata: Feature metadata from training
    
    Returns:
        features_df: DataFrame with engineered features
    """
    log("Engineering features...", 'DEBUG')
    
    df_features = df.copy()
    
    # Ensure InvoiceDate is datetime
    if df_features['InvoiceDate'].dtype == 'object':
        df_features['InvoiceDate'] = pd.to_datetime(df_features['InvoiceDate'])
    
    # ==========================================
    # NUMERICAL FEATURES
    # ==========================================
    
    df_features['Price_clean'] = pd.to_numeric(df_features['Price'], errors='coerce').fillna(0)
    df_features['Quantity_clean'] = pd.to_numeric(df_features['Quantity'], errors='coerce').fillna(0)
    
    df_features['TotalAmount'] = df_features['Price_clean'] * df_features['Quantity_clean']
    df_features['AbsQuantity'] = df_features['Quantity_clean'].abs()
    df_features['AbsPrice'] = df_features['Price_clean'].abs()
    
    # ==========================================
    # PATTERN DETECTION FEATURES
    # ==========================================
    
    df_features['is_decimal_qty'] = ((df_features['Quantity_clean'] % 1) != 0).astype(int)
    df_features['is_round_price'] = df_features['Price_clean'].isin([100.0, 200.0, 500.0, 1000.0, 5000.0]).astype(int)
    df_features['is_round_qty'] = df_features['AbsQuantity'].isin([100.0, 500.0, 1000.0, 5000.0, 10000.0]).astype(int)
    df_features['high_price_low_qty'] = ((df_features['Price_clean'] > 100) & (df_features['AbsQuantity'] < 10)).astype(int)
    df_features['low_price_high_qty'] = ((df_features['Price_clean'] < 1) & (df_features['AbsQuantity'] > 1000)).astype(int)
    df_features['is_extreme_price'] = (df_features['Price_clean'] > 200).astype(int)
    df_features['is_extreme_qty'] = (df_features['AbsQuantity'] > 500).astype(int)
    
    # ==========================================
    # TEMPORAL FEATURES
    # ==========================================
    
    df_features['Hour'] = df_features['InvoiceDate'].dt.hour
    df_features['DayOfWeek'] = df_features['InvoiceDate'].dt.dayofweek
    df_features['Month'] = df_features['InvoiceDate'].dt.month
    df_features['DayOfMonth'] = df_features['InvoiceDate'].dt.day
    df_features['IsWeekend'] = (df_features['DayOfWeek'] >= 5).astype(int)
    
    # ==========================================
    # CATEGORICAL FEATURES
    # ==========================================
    
    df_features['IsCancellation'] = df_features['Invoice'].str.startswith('C').astype(int)
    
    df_features['PriceSign'] = np.where(df_features['Price_clean'] > 0, 1,
                                        np.where(df_features['Price_clean'] < 0, -1, 0))
    df_features['QuantitySign'] = np.where(df_features['Quantity_clean'] > 0, 1,
                                           np.where(df_features['Quantity_clean'] < 0, -1, 0))
    
    stockcode_freq = metadata.get('stockcode_freq', {})
    df_features['StockCode_freq'] = df_features['StockCode'].map(stockcode_freq).fillna(0)
    
    top_countries = metadata.get('top_countries', [])
    for country in top_countries:
        df_features[f'Country_{country}'] = (df_features['Country'] == country).astype(int)
    df_features['Country_Other'] = (~df_features['Country'].isin(top_countries)).astype(int)
    
    # ==========================================
    # SELECT FINAL FEATURES
    # ==========================================
    
    feature_columns = metadata['feature_columns']
    features_df = df_features[feature_columns].copy()
    features_df = features_df.fillna(0)
    
    log(f"Engineered {len(feature_columns)} features for {len(df)} rows", 'DEBUG')
    
    return features_df


def lambda_handler(event, context):
    """
    ML-based anomaly detection Lambda
    Triggered by CleanZone-RulesBased/ Parquet uploads
    """
    log("=== ML Anomaly Detection Lambda Started ===", 'INFO')
    
    # Parse S3 event
    try:
        record = event['Records'][0]
        source_bucket = record['s3']['bucket']['name']
        source_key = record['s3']['object']['key']
        file_name = os.path.basename(source_key)
        
        log(f"Processing: s3://{source_bucket}/{source_key}", 'INFO')
        
        # Validate prefix (both clean and anomalies)
        if not (source_key.startswith('CleanZone-RulesBased/') or 
                source_key.startswith('CleanZone-RulesBased-Anomalies/')):
            log(f"File not in CleanZone-RulesBased/ or CleanZone-RulesBased-Anomalies/. Ignoring.", 'INFO')
            return {'statusCode': 200, 'body': 'File not in expected prefix.'}
        
        # Determine data type and output path
        is_anomalous = 'Anomalies' in source_key or 'anomalies' in source_key
        data_type = 'anomalies' if is_anomalous else 'clean'
        
        # Set output path based on data type
        if is_anomalous:
            output_prefix = 'CleanZone-Final-Anomalies/'
        else:
            output_prefix = 'CleanZone-Final/'
            
    except Exception as e:
        log(f"ERROR parsing S3 event: {e}", 'ERROR')
        return {'statusCode': 400, 'body': 'Invalid S3 event.'}
    
    # Download Parquet from S3
    temp_parquet = f'/tmp/{file_name}'
    try:
        log(f"Downloading Parquet...", 'DEBUG')
        s3_client.download_file(source_bucket, source_key, temp_parquet)
        log(f"Downloaded: {os.path.getsize(temp_parquet)} bytes", 'DEBUG')
    except Exception as e:
        log(f"ERROR downloading: {e}", 'ERROR')
        return {'statusCode': 500, 'body': 'Failed to download Parquet.'}
    
    # Initialize metrics
    metrics = {
        'timestamp': datetime.utcnow().isoformat(),
        'source_file': source_key,
        'data_type': data_type,
        'initial_record_count': 0,
        'final_record_count': 0,
        'ml_flagged_count': 0,
        'flagged_row_ids': [],
        'processing_time_sec': 0.0
    }
    
    process_start = datetime.utcnow()
    
    try:
        # Load model
        model, metadata = load_model_from_s3()
        log("Model loaded", 'DEBUG')
        
        # Load Parquet data
        df = pd.read_parquet(temp_parquet)
        initial_count = len(df)
        metrics['initial_record_count'] = initial_count
        log(f"Loaded {initial_count:,} records from Parquet", 'INFO')
        
        # Preserve __row_id from upstream (Rule Lambda)
        # This ensures ML flagged IDs map to original dataset
        if '__row_id' not in df.columns:
            # Shouldn't happen in your pipeline, but handle gracefully
            log("WARNING: __row_id not found, creating new sequential IDs", 'INFO')
            df['__row_id'] = range(len(df))
        else:
            # Use existing __row_id from Rule Lambda (maps to original CSV position)
            row_id_min = df['__row_id'].min()
            row_id_max = df['__row_id'].max()
            log(f"Preserving __row_id from upstream (range: {row_id_min}-{row_id_max})", 'DEBUG')
        
        # Engineer features
        X = engineer_features(df, metadata)
        
        # Run ML inference
        log("Running Isolation Forest inference...", 'DEBUG')
        predictions = model.predict(X)
        scores = model.decision_function(X)
        
        # Flag anomalies (prediction = -1)
        anomaly_mask = predictions == -1
        flagged_row_ids = df.loc[anomaly_mask, '__row_id'].tolist()
        
        metrics['ml_flagged_count'] = len(flagged_row_ids)
        metrics['flagged_row_ids'] = flagged_row_ids
        
        log(f"ML flagged {len(flagged_row_ids):,} anomalies", 'INFO')
        
        # Keep only normal records (prediction = 1)
        df_clean = df[~anomaly_mask].copy()
        
        # Remove __row_id before saving
        df_clean = df_clean.drop(columns=['__row_id'])
        
        final_count = len(df_clean)
        metrics['final_record_count'] = final_count
        
        log(f"Removed {initial_count - final_count:,} records", 'INFO')
        
        # Save to CleanZone-Final or CleanZone-Final-Anomalies
        if final_count > 0:
            # Replace RulesBased with Final, preserve -Anomalies suffix if present
            if is_anomalous:
                output_key = source_key.replace('CleanZone-RulesBased-Anomalies/', 'CleanZone-Final-Anomalies/')
            else:
                output_key = source_key.replace('CleanZone-RulesBased/', 'CleanZone-Final/')
            
            temp_output = '/tmp/output.parquet'
            
            df_clean.to_parquet(temp_output, index=False)
            s3_client.upload_file(temp_output, BUCKET_NAME, output_key)
            
            log(f"Uploaded: s3://{BUCKET_NAME}/{output_key}", 'INFO')
            
            os.remove(temp_output)
        else:
            log("WARNING: All records flagged as anomalies", 'INFO')
        
    except Exception as e:
        log(f"ERROR during processing: {e}", 'ERROR')
        import traceback
        traceback.print_exc()
        if os.path.exists(temp_parquet):
            os.remove(temp_parquet)
        return {'statusCode': 500, 'body': f'Processing failed: {str(e)}'}
    
    # Cleanup
    if os.path.exists(temp_parquet):
        os.remove(temp_parquet)
    
    # Finalize metrics
    process_end = datetime.utcnow()
    metrics['processing_time_sec'] = round((process_end - process_start).total_seconds(), 3)
    
    # Save metrics to S3
    base_name = os.path.splitext(file_name)[0]
    metrics_key = f"metrics/ml/{data_type}/{datetime.utcnow().strftime('%Y/%m/%d')}/{base_name}_{process_start.strftime('%H%M%S')}.json"
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=metrics_key,
        Body=json.dumps(metrics, indent=2)
    )
    
    log(f"Metrics saved: s3://{BUCKET_NAME}/{metrics_key}", 'DEBUG')
    log("=== ML Pipeline Complete ===", 'INFO')
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'ML processing complete',
            'data_type': data_type,
            'records_processed': final_count,
            'ml_flagged': metrics['ml_flagged_count'],
            'metrics_location': f"s3://{BUCKET_NAME}/{metrics_key}"
        })
    }