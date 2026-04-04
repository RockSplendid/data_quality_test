"""
Anomaly Injection Script with Ground Truth Tracking
Injects business rule violations and tracks which rows were corrupted
for Precision/Recall/F1 evaluation
"""

import pandas as pd
import numpy as np
import boto3
import os
import json
from datetime import datetime, timedelta

# Configuration
BUCKET_NAME = 'datasourcebucket1109'
LOCAL_CLEAN_FILE = 'online_retail_II.csv'
OUTPUT_FILE = 'online_retail_II_anomalies.csv'
GROUND_TRUTH_FILE = 'online_retail_II_ground_truth.json'
S3_UPLOAD_KEY = 'RawZone-Anomalies/online_retail_II_anomalies.csv'
S3_GROUND_TRUTH_KEY = 'RawZone-Anomalies/online_retail_II_ground_truth.json'

s3_client = boto3.client('s3')


def inject_anomalies(df):
    """
    Inject PHASE 1 anomalies: Business Rule Violations
    Returns: df_anomaly, ground_truth dict
    """
    
    print("\n" + "="*60)
    print("🔧 INJECTING PHASE 1 ANOMALIES: BUSINESS RULE VIOLATIONS")
    print("="*60)
    
    df_anomaly = df.copy()
    # Add unique row ID for tracking
    df_anomaly['__row_id'] = range(len(df_anomaly))
    
    original_len = len(df_anomaly)
    
    # Ground truth: track which rows are anomalies and why
    ground_truth = {
        'total_rows': original_len,
        'total_anomalies_injected': 0,
        'anomaly_indices': [],  # List of row IDs that were corrupted
        'anomaly_details': {},  # {row_id: [list of violation types]}
        'injection_summary': {}
    }
    
    anomalies_injected = {}
    
    # ==================================================================
    # PHASE 1: BUSINESS RULE VIOLATIONS
    # ==================================================================
    
    print("\n📌 Phase 1: Business Rule Violations")
    
    # 1. Cancellation invoices with POSITIVE quantities (VIOLATION)
    cancellation_mask = df_anomaly['Invoice'].astype(str).str.startswith('C')
    cancellation_indices = df_anomaly[cancellation_mask & (df_anomaly['Quantity'] < 0)].index
    
    if len(cancellation_indices) > 0:
        violation_size = min(int(len(cancellation_indices) * 0.10), 1000)
        violation_idx = np.random.choice(cancellation_indices, violation_size, replace=False)
        
        # Track ground truth
        for idx in violation_idx:
            row_id = int(df_anomaly.loc[idx, '__row_id'])
            ground_truth['anomaly_indices'].append(row_id)
            if row_id not in ground_truth['anomaly_details']:
                ground_truth['anomaly_details'][row_id] = []
            ground_truth['anomaly_details'][row_id].append('cancellation_positive_qty')
        
        # Inject anomaly
        df_anomaly.loc[violation_idx, 'Quantity'] = abs(df_anomaly.loc[violation_idx, 'Quantity'])
        anomalies_injected['Cancellation with Positive Quantity'] = violation_size
        print(f"  ✓ Injected {violation_size:,} cancellations with positive quantity")
    
    # 2. Regular invoices with NEGATIVE quantities (VIOLATION)
    regular_mask = ~df_anomaly['Invoice'].astype(str).str.startswith('C')
    regular_with_positive = df_anomaly[regular_mask & (df_anomaly['Quantity'] > 0)].index
    
    if len(regular_with_positive) > 0:
        violation_size = int(len(df_anomaly) * 0.008)  # 0.8%
        violation_idx = np.random.choice(regular_with_positive, 
                                        min(violation_size, len(regular_with_positive)), 
                                        replace=False)
        
        # Track ground truth
        for idx in violation_idx:
            row_id = int(df_anomaly.loc[idx, '__row_id'])
            if row_id not in ground_truth['anomaly_indices']:
                ground_truth['anomaly_indices'].append(row_id)
            if row_id not in ground_truth['anomaly_details']:
                ground_truth['anomaly_details'][row_id] = []
            ground_truth['anomaly_details'][row_id].append('regular_negative_qty')
        
        # Inject anomaly
        df_anomaly.loc[violation_idx, 'Quantity'] = -1 * df_anomaly.loc[violation_idx, 'Quantity']
        anomalies_injected['Regular Invoice with Negative Quantity'] = len(violation_idx)
        print(f"  ✓ Injected {len(violation_idx):,} regular invoices with negative quantity")
    
    # 3. Zero quantities (VIOLATION)
    zero_qty_size = int(len(df_anomaly) * 0.005)  # 0.5%
    zero_idx = np.random.choice(df_anomaly.index, zero_qty_size, replace=False)
    
    # Track ground truth
    for idx in zero_idx:
        row_id = int(df_anomaly.loc[idx, '__row_id'])
        if row_id not in ground_truth['anomaly_indices']:
            ground_truth['anomaly_indices'].append(row_id)
        if row_id not in ground_truth['anomaly_details']:
            ground_truth['anomaly_details'][row_id] = []
        ground_truth['anomaly_details'][row_id].append('zero_quantity')
    
    # Inject anomaly
    df_anomaly.loc[zero_idx, 'Quantity'] = 0
    anomalies_injected['Zero Quantities'] = zero_qty_size
    print(f"  ✓ Injected {zero_qty_size:,} zero quantities")
    
    # Finalize ground truth
    ground_truth['anomaly_indices'] = sorted(list(set(ground_truth['anomaly_indices'])))
    ground_truth['total_anomalies_injected'] = len(ground_truth['anomaly_indices'])
    ground_truth['injection_summary'] = anomalies_injected
    
    # Convert anomaly_details keys to strings for JSON compatibility
    ground_truth['anomaly_details'] = {str(k): v for k, v in ground_truth['anomaly_details'].items()}
    
    # Summary
    print("\n" + "="*60)
    print("📊 INJECTION SUMMARY")
    print("="*60)
    print(f"  Original rows: {original_len:,}")
    print(f"  Final rows: {len(df_anomaly):,}")
    print(f"  Total unique anomalies injected: {ground_truth['total_anomalies_injected']:,}")
    
    print("\n🔍 Anomaly Breakdown:")
    for anomaly_type, count in anomalies_injected.items():
        print(f"  • {anomaly_type}: {count:,}")
    
    return df_anomaly, ground_truth


def main():
    """Main execution"""
    
    print("\n" + "="*60)
    print("🚀 ANOMALY INJECTION WITH GROUND TRUTH TRACKING")
    print("="*60)
    
    # 1. Load clean data
    print(f"\n📂 Loading clean data from: {LOCAL_CLEAN_FILE}")
    try:
        df = pd.read_csv(LOCAL_CLEAN_FILE)
        if ' ' in df.columns[0]:
            df.columns = df.columns.str.replace(' ', '')
        print(f"✓ Loaded {len(df):,} rows")
    except FileNotFoundError:
        print(f"❌ ERROR: File '{LOCAL_CLEAN_FILE}' not found!")
        print("\nOptions:")
        print(f"  1. Update LOCAL_CLEAN_FILE variable in this script")
        print(f"  2. Download from S3:")
        print(f"     aws s3 cp s3://{BUCKET_NAME}/RawZone/online_retail_II.csv .")
        return
    
    # 2. Inject anomalies and get ground truth
    df_anomalous, ground_truth = inject_anomalies(df)
    
    # Remove the temporary __row_id column before saving
    df_anomalous = df_anomalous.drop(columns=['__row_id'])
    
    # 3. Save anomalous data locally
    print(f"\n💾 Saving anomalous data locally: {OUTPUT_FILE}")
    df_anomalous.to_csv(OUTPUT_FILE, index=False)
    file_size = os.path.getsize(OUTPUT_FILE) / (1024 * 1024)
    print(f"✓ Saved: {file_size:.2f} MB")
    
    # 4. Save ground truth locally
    print(f"\n💾 Saving ground truth: {GROUND_TRUTH_FILE}")
    with open(GROUND_TRUTH_FILE, 'w') as f:
        json.dump(ground_truth, f, indent=2)
    print(f"✓ Ground truth saved with {ground_truth['total_anomalies_injected']:,} anomaly labels")
    
    # 5. Upload anomalous data to S3
    print(f"\n☁️  Uploading anomalous data to S3: s3://{BUCKET_NAME}/{S3_UPLOAD_KEY}")
    try:
        s3_client.upload_file(OUTPUT_FILE, BUCKET_NAME, S3_UPLOAD_KEY)
        print(f"✓ Upload successful!")
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        return
    
    # 6. Upload ground truth to S3
    print(f"\n☁️  Uploading ground truth to S3: s3://{BUCKET_NAME}/{S3_GROUND_TRUTH_KEY}")
    try:
        s3_client.upload_file(GROUND_TRUTH_FILE, BUCKET_NAME, S3_GROUND_TRUTH_KEY)
        print(f"✓ Ground truth uploaded!")
    except Exception as e:
        print(f"❌ Ground truth upload failed: {e}")
        return
    
    # 7. Create summary
    summary_file = OUTPUT_FILE.replace('.csv', '_summary.txt')
    with open(summary_file, 'w') as f:
        f.write("ANOMALY INJECTION SUMMARY WITH GROUND TRUTH\n")
        f.write("="*60 + "\n\n")
        f.write(f"Timestamp: {datetime.utcnow().isoformat()}\n")
        f.write(f"Source file: {LOCAL_CLEAN_FILE}\n")
        f.write(f"Output file: {OUTPUT_FILE}\n")
        f.write(f"Ground truth file: {GROUND_TRUTH_FILE}\n")
        f.write(f"S3 location: s3://{BUCKET_NAME}/{S3_UPLOAD_KEY}\n")
        f.write(f"Ground truth S3: s3://{BUCKET_NAME}/{S3_GROUND_TRUTH_KEY}\n\n")
        f.write(f"Original rows: {len(df):,}\n")
        f.write(f"Final rows: {len(df_anomalous):,}\n")
        f.write(f"Total unique anomalies injected: {ground_truth['total_anomalies_injected']:,}\n\n")
        f.write("PHASE 1: Business Rule Violations\n")
        f.write("-" * 60 + "\n")
        for anomaly_type, count in ground_truth['injection_summary'].items():
            f.write(f"  • {anomaly_type}: {count:,}\n")
    
    print(f"\n📄 Summary saved: {summary_file}")
    
    # 8. Next steps
    print("\n" + "="*60)
    print("✨ NEXT STEPS")
    print("="*60)
    print("1. Lambda will process the uploaded file automatically")
    print("2. Lambda will save flagged row indices in metrics")
    print("3. Run evaluate_performance.py to calculate Precision/Recall/F1")
    print("\nGround truth is now available for ML comparison!")


if __name__ == "__main__":
    main()