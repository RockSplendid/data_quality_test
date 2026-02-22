"""
Anomaly Injection Script for Data Quality Pipeline Testing
Injects business rule violations and uploads to S3 RawZone-Anomalies/
"""

import pandas as pd
import numpy as np
import boto3
import os
from datetime import datetime, timedelta, timezone

# Configuration
BUCKET_NAME = 'datasourcebucket1109'
LOCAL_CLEAN_FILE = 'online_retail_II.csv'  # Your clean local file
OUTPUT_FILE = 'online_retail_II_anomalies.csv'
S3_UPLOAD_KEY = 'RawZone-Anomalies/online_retail_II_anomalies.csv'

s3_client = boto3.client('s3')


def inject_anomalies(df):
    """Inject PHASE 1 anomalies: Business Rule Violations"""
    
    print("\n" + "="*60)
    print("🔧 INJECTING PHASE 1 ANOMALIES: BUSINESS RULE VIOLATIONS")
    print("="*60)
    
    df_anomaly = df.copy()
    original_len = len(df_anomaly)
    
    anomalies_injected = {}
    
    # ==================================================================
    # PHASE 1: BUSINESS RULE VIOLATIONS
    # ==================================================================
    
    print("\n📌 Phase 1: Business Rule Violations")
    
    # 1. Cancellation invoices with POSITIVE quantities (VIOLATION)
    # Rule: Invoices starting with 'C' should have negative quantities
    cancellation_mask = df_anomaly['Invoice'].astype(str).str.startswith('C')
    cancellation_indices = df_anomaly[cancellation_mask & (df_anomaly['Quantity'] < 0)].index
    
    if len(cancellation_indices) > 0:
        violation_size = min(int(len(cancellation_indices) * 0.10), 1000)  # 10%
        violation_idx = np.random.choice(cancellation_indices, violation_size, replace=False)
        df_anomaly.loc[violation_idx, 'Quantity'] = abs(df_anomaly.loc[violation_idx, 'Quantity'])
        anomalies_injected['Cancellation with Positive Quantity'] = violation_size
        print(f"  ✓ Injected {violation_size:,} cancellations with positive quantity")
    
    # 2. Regular invoices with NEGATIVE quantities (VIOLATION)
    # Rule: Regular invoices should have positive quantities
    regular_mask = ~df_anomaly['Invoice'].astype(str).str.startswith('C')
    regular_with_positive = df_anomaly[regular_mask & (df_anomaly['Quantity'] > 0)].index
    
    if len(regular_with_positive) > 0:
        violation_size = int(len(df_anomaly) * 0.008)  # 0.8%
        violation_idx = np.random.choice(regular_with_positive, 
                                        min(violation_size, len(regular_with_positive)), 
                                        replace=False)
        df_anomaly.loc[violation_idx, 'Quantity'] = -1 * df_anomaly.loc[violation_idx, 'Quantity']
        anomalies_injected['Regular Invoice with Negative Quantity'] = len(violation_idx)
        print(f"  ✓ Injected {len(violation_idx):,} regular invoices with negative quantity")
    
    # 3. Zero quantities (VIOLATION)
    # Rule: Quantity cannot be zero
    zero_qty_size = int(len(df_anomaly) * 0.005)  # 0.5%
    zero_idx = np.random.choice(df_anomaly.index, zero_qty_size, replace=False)
    df_anomaly.loc[zero_idx, 'Quantity'] = 0
    anomalies_injected['Zero Quantities'] = zero_qty_size
    print(f"  ✓ Injected {zero_qty_size:,} zero quantities")
    
    # ==================================================================
    # Summary
    # ==================================================================
    
    print("\n" + "="*60)
    print("📊 INJECTION SUMMARY")
    print("="*60)
    print(f"  Original rows: {original_len:,}")
    print(f"  Final rows: {len(df_anomaly):,}")
    print(f"  Total anomalies injected: {sum(anomalies_injected.values()):,}")
    
    print("\n🔍 Anomaly Breakdown:")
    for anomaly_type, count in anomalies_injected.items():
        print(f"  • {anomaly_type}: {count:,}")
    
    return df_anomaly, anomalies_injected


def main():
    """Main execution"""
    
    print("\n" + "="*60)
    print("🚀 ANOMALY INJECTION & S3 UPLOAD SCRIPT")
    print("="*60)
    
    # 1. Load clean data
    print(f"\n📂 Loading clean data from: {LOCAL_CLEAN_FILE}")
    try:
        df = pd.read_csv(LOCAL_CLEAN_FILE)
        # Clean column names if needed
        if ' ' in df.columns[0]:
            df.columns = df.columns.str.replace(' ', '')
        print(f"✓ Loaded {len(df):,} rows")
    except FileNotFoundError:
        print(f"❌ ERROR: File '{LOCAL_CLEAN_FILE}' not found!")
        print("\nOptions:")
        print("  1. Update LOCAL_CLEAN_FILE variable in this script")
        print("  2. Download from S3 first using AWS CLI:")
        print(f"     aws s3 cp s3://{BUCKET_NAME}/RawZone/online_retail_II.csv .")
        return
    
    # 2. Inject anomalies
    df_anomalous, anomaly_summary = inject_anomalies(df)
    
    # 3. Save locally
    print(f"\n💾 Saving anomalous data locally: {OUTPUT_FILE}")
    df_anomalous.to_csv(OUTPUT_FILE, index=False)
    file_size = os.path.getsize(OUTPUT_FILE) / (1024 * 1024)  # MB
    print(f"✓ Saved: {file_size:.2f} MB")
    
    # 4. Upload to S3
    print(f"\n☁️  Uploading to S3: s3://{BUCKET_NAME}/{S3_UPLOAD_KEY}")
    try:
        s3_client.upload_file(OUTPUT_FILE, BUCKET_NAME, S3_UPLOAD_KEY)
        print(f"✓ Upload successful!")
        print(f"\n📍 File location: s3://{BUCKET_NAME}/{S3_UPLOAD_KEY}")
        print(f"   This will trigger Lambda processing automatically.")
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        print("\nPlease check:")
        print("  1. AWS credentials are configured (aws configure)")
        print("  2. Bucket name is correct")
        print("  3. You have S3 write permissions")
        return
    
    # 5. Create summary file
    summary_file = OUTPUT_FILE.replace('.csv', '_summary.txt')
    with open(summary_file, 'w') as f:
        f.write("ANOMALY INJECTION SUMMARY\n")
        f.write("="*60 + "\n\n")
        f.write(f"Timestamp: {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"Source file: {LOCAL_CLEAN_FILE}\n")
        f.write(f"Output file: {OUTPUT_FILE}\n")
        f.write(f"S3 location: s3://{BUCKET_NAME}/{S3_UPLOAD_KEY}\n\n")
        f.write(f"Original rows: {len(df):,}\n")
        f.write(f"Final rows: {len(df_anomalous):,}\n\n")
        f.write("PHASE 1: Business Rule Violations\n")
        f.write("-" * 60 + "\n")
        for anomaly_type, count in anomaly_summary.items():
            f.write(f"  • {anomaly_type}: {count:,}\n")
    
    print(f"\n📄 Summary saved: {summary_file}")
    
    # 6. Next steps
    print("\n" + "="*60)
    print("✨ NEXT STEPS")
    print("="*60)
    print("1. Lambda will automatically process the uploaded file")
    print("2. Check CloudWatch Logs for execution details")
    print("3. Processed data will be in: CleanZone-Anomalies/")
    print(f"4. Metrics will be in: metrics/anomalies/")
    print("\nTo compare with clean data:")
    print(f"  - Clean metrics: metrics/clean/")
    print(f"  - Anomaly metrics: metrics/anomalies/")


if __name__ == "__main__":
    main()