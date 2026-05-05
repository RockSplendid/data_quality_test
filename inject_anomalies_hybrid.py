"""
Anomaly Injection Script v4 - True Outliers
Uses percentile-based approach and unusual patterns
to create anomalies that ML will actually detect
"""

import pandas as pd
import numpy as np
import boto3
import os
import json
from io import BytesIO
from datetime import datetime

# Configuration
BUCKET_NAME = 'datasourcebucket1109'
S3_CLEAN_KEY = 'RawZone/online_retail_II.csv'
OUTPUT_FILE = 'online_retail_II_anomalies.csv'
GROUND_TRUTH_FILE = 'online_retail_II_ground_truth.json'
S3_UPLOAD_KEY = 'RawZone-Anomalies/online_retail_II_anomalies.csv'
S3_GROUND_TRUTH_KEY = 'RawZone-Anomalies/online_retail_II_ground_truth.json'

s3_client = boto3.client('s3')


def inject_anomalies(df):
    """
    Inject BOTH rule-based AND ML-detectable anomalies
    ML anomalies use percentile-based approach for TRUE outliers
    """
    
    print("\n" + "="*70)
    print("🔧 INJECTING ANOMALIES v4: PERCENTILE-BASED TRUE OUTLIERS")
    print("="*70)
    
    df_anomaly = df.copy()
    
    # Clean column names
    if ' ' in df_anomaly.columns[0]:
        df_anomaly.columns = df_anomaly.columns.str.replace(' ', '')
    
    # Add unique row ID for tracking
    df_anomaly['__row_id'] = range(len(df_anomaly))
    
    original_len = len(df_anomaly)
    
    # Calculate percentiles for reference
    price_p99 = df_anomaly[df_anomaly['Price'] > 0]['Price'].quantile(0.99)
    qty_p99 = df_anomaly[df_anomaly['Quantity'] > 0]['Quantity'].quantile(0.99)
    
    print(f"\n📊 Data Distribution:")
    print(f"  Price 99th percentile: {price_p99:.2f}")
    print(f"  Quantity 99th percentile: {qty_p99:.0f}")
    
    # Ground truth tracking
    ground_truth = {
        'total_rows': original_len,
        'total_anomalies_injected': 0,
        'anomaly_indices': [],
        'anomaly_details': {},
        'injection_summary': {
            'rule_based': {},
            'ml_detectable': {}
        }
    }
    
    anomalies_injected = {
        'rule_based': {},
        'ml_detectable': {}
    }
    
    # Track corrupted indices
    corrupted_indices = set()
    
    # ==================================================================
    # TYPE A: RULE-BASED ANOMALIES
    # ==================================================================
    
    print("\n📌 Type A: Rule-Based Anomalies")
    print("-" * 70)
    
    # A1. Cancellation with positive qty
    cancellation_mask = df_anomaly['Invoice'].astype(str).str.startswith('C')
    cancellation_candidates = df_anomaly[
        cancellation_mask & 
        (df_anomaly['Quantity'] < 0) & 
        (~df_anomaly.index.isin(corrupted_indices))
    ].index
    
    if len(cancellation_candidates) > 0:
        violation_size = min(int(len(cancellation_candidates) * 0.10), 500)
        violation_idx = np.random.choice(cancellation_candidates, violation_size, replace=False)
        
        for idx in violation_idx:
            row_id = int(df_anomaly.loc[idx, '__row_id'])
            ground_truth['anomaly_indices'].append(row_id)
            if str(row_id) not in ground_truth['anomaly_details']:
                ground_truth['anomaly_details'][str(row_id)] = []
            ground_truth['anomaly_details'][str(row_id)].append('rule_cancellation_positive_qty')
            corrupted_indices.add(idx)
        
        df_anomaly.loc[violation_idx, 'Quantity'] = abs(df_anomaly.loc[violation_idx, 'Quantity'])
        anomalies_injected['rule_based']['Cancellation_Positive_Qty'] = violation_size
        print(f"  ✓ A1: Cancellation positive qty: {violation_size:,}")
    
    # A2. Regular with negative qty
    regular_mask = ~df_anomaly['Invoice'].astype(str).str.startswith('C')
    regular_candidates = df_anomaly[
        regular_mask & 
        (df_anomaly['Quantity'] > 0) & 
        (~df_anomaly.index.isin(corrupted_indices))
    ].index
    
    if len(regular_candidates) > 0:
        violation_size = min(int(len(df_anomaly) * 0.005), 300)
        violation_idx = np.random.choice(regular_candidates, 
                                        min(violation_size, len(regular_candidates)), 
                                        replace=False)
        
        for idx in violation_idx:
            row_id = int(df_anomaly.loc[idx, '__row_id'])
            ground_truth['anomaly_indices'].append(row_id)
            if str(row_id) not in ground_truth['anomaly_details']:
                ground_truth['anomaly_details'][str(row_id)] = []
            ground_truth['anomaly_details'][str(row_id)].append('rule_regular_negative_qty')
            corrupted_indices.add(idx)
        
        df_anomaly.loc[violation_idx, 'Quantity'] = -1 * df_anomaly.loc[violation_idx, 'Quantity']
        anomalies_injected['rule_based']['Regular_Negative_Qty'] = len(violation_idx)
        print(f"  ✓ A2: Regular negative qty: {len(violation_idx):,}")
    
    # A3. Zero quantities
    zero_candidates = df_anomaly[~df_anomaly.index.isin(corrupted_indices)].index
    
    if len(zero_candidates) > 0:
        violation_size = min(int(len(df_anomaly) * 0.003), 200)
        violation_idx = np.random.choice(zero_candidates, violation_size, replace=False)
        
        for idx in violation_idx:
            row_id = int(df_anomaly.loc[idx, '__row_id'])
            ground_truth['anomaly_indices'].append(row_id)
            if str(row_id) not in ground_truth['anomaly_details']:
                ground_truth['anomaly_details'][str(row_id)] = []
            ground_truth['anomaly_details'][str(row_id)].append('rule_zero_quantity')
            corrupted_indices.add(idx)
        
        df_anomaly.loc[violation_idx, 'Quantity'] = 0
        anomalies_injected['rule_based']['Zero_Quantity'] = violation_size
        print(f"  ✓ A3: Zero quantities: {violation_size:,}")
    
    # ==================================================================
    # TYPE B: ML-DETECTABLE ANOMALIES (Percentile-Based TRUE Outliers)
    # ==================================================================
    
    print("\n📌 Type B: ML-Detectable Anomalies (TRUE Outliers)")
    print("-" * 70)
    
    # B1. Extreme Prices (10x-50x the 99th percentile)
    price_candidates = df_anomaly[
        (df_anomaly['Price'] > 0) & 
        (~df_anomaly.index.isin(corrupted_indices))
    ].copy()
    
    if len(price_candidates) > 0:
        violation_size = min(int(len(df_anomaly) * 0.004), 250)
        violation_idx = np.random.choice(price_candidates.index, violation_size, replace=False)
        
        for idx in violation_idx:
            row_id = int(df_anomaly.loc[idx, '__row_id'])
            ground_truth['anomaly_indices'].append(row_id)
            if str(row_id) not in ground_truth['anomaly_details']:
                ground_truth['anomaly_details'][str(row_id)] = []
            ground_truth['anomaly_details'][str(row_id)].append('ml_extreme_price')
            corrupted_indices.add(idx)
        
        # Set price to 10x-50x the 99th percentile
        multipliers = np.random.uniform(10, 50, len(violation_idx))
        df_anomaly.loc[violation_idx, 'Price'] = price_p99 * multipliers
        
        anomalies_injected['ml_detectable']['Extreme_Price_P99'] = violation_size
        print(f"  ✓ B1: Extreme prices (10x-50x P99={price_p99:.2f}): {violation_size:,}")
        print(f"       Range: {(price_p99*10):.2f} - {(price_p99*50):.2f}")
    
    # B2. Extreme Quantities (10x-50x the 99th percentile)
    qty_candidates = df_anomaly[
        (df_anomaly['Quantity'] > 0) & 
        (~df_anomaly.index.isin(corrupted_indices))
    ].copy()
    
    if len(qty_candidates) > 0:
        violation_size = min(int(len(df_anomaly) * 0.004), 250)
        violation_idx = np.random.choice(qty_candidates.index, violation_size, replace=False)
        
        for idx in violation_idx:
            row_id = int(df_anomaly.loc[idx, '__row_id'])
            ground_truth['anomaly_indices'].append(row_id)
            if str(row_id) not in ground_truth['anomaly_details']:
                ground_truth['anomaly_details'][str(row_id)] = []
            ground_truth['anomaly_details'][str(row_id)].append('ml_extreme_quantity')
            corrupted_indices.add(idx)
        
        # Set quantity to 10x-50x the 99th percentile
        multipliers = np.random.randint(10, 51, len(violation_idx))
        df_anomaly.loc[violation_idx, 'Quantity'] = (qty_p99 * multipliers).astype(int)
        
        anomalies_injected['ml_detectable']['Extreme_Quantity_P99'] = violation_size
        print(f"  ✓ B2: Extreme quantities (10x-50x P99={qty_p99:.0f}): {violation_size:,}")
        print(f"       Range: {int(qty_p99*10)} - {int(qty_p99*50)}")
    
    # B3. Extreme TotalAmount (set to >99.9th percentile)
    amount_candidates = df_anomaly[
        (df_anomaly['Price'] > 0) & 
        (df_anomaly['Quantity'] > 0) &
        (~df_anomaly.index.isin(corrupted_indices))
    ].copy()
    
    if len(amount_candidates) > 0:
        violation_size = min(int(len(df_anomaly) * 0.003), 200)
        violation_idx = np.random.choice(amount_candidates.index, violation_size, replace=False)
        
        for idx in violation_idx:
            row_id = int(df_anomaly.loc[idx, '__row_id'])
            ground_truth['anomaly_indices'].append(row_id)
            if str(row_id) not in ground_truth['anomaly_details']:
                ground_truth['anomaly_details'][str(row_id)] = []
            ground_truth['anomaly_details'][str(row_id)].append('ml_extreme_total')
            corrupted_indices.add(idx)
        
        # Set both to create extreme total amounts
        df_anomaly.loc[violation_idx, 'Price'] = price_p99 * np.random.uniform(5, 20, len(violation_idx))
        df_anomaly.loc[violation_idx, 'Quantity'] = (qty_p99 * np.random.randint(5, 21, len(violation_idx))).astype(int)
        
        anomalies_injected['ml_detectable']['Extreme_Total_Amount'] = violation_size
        print(f"  ✓ B3: Extreme total amounts: {violation_size:,}")
    
    # B4. Statistical Outliers - Unusual Price/Quantity Ratio
    ratio_candidates = df_anomaly[
        (df_anomaly['Price'] > 0) & 
        (df_anomaly['Quantity'] > 0) &
        (~df_anomaly.index.isin(corrupted_indices))
    ].copy()
    
    if len(ratio_candidates) > 0:
        violation_size = min(int(len(df_anomaly) * 0.003), 150)
        violation_idx = np.random.choice(ratio_candidates.index, violation_size, replace=False)
        
        for idx in violation_idx:
            row_id = int(df_anomaly.loc[idx, '__row_id'])
            ground_truth['anomaly_indices'].append(row_id)
            if str(row_id) not in ground_truth['anomaly_details']:
                ground_truth['anomaly_details'][str(row_id)] = []
            ground_truth['anomaly_details'][str(row_id)].append('ml_unusual_ratio')
            corrupted_indices.add(idx)
        
        # Create unusual ratio: very high price, qty=1 OR very low price, high qty
        for i, idx in enumerate(violation_idx):
            if i % 2 == 0:
                # Pattern 1: Expensive item, qty=1 (rare luxury purchase)
                df_anomaly.loc[idx, 'Price'] = price_p99 * np.random.uniform(20, 100)
                df_anomaly.loc[idx, 'Quantity'] = 1
            else:
                # Pattern 2: Cheap item, massive qty (unusual bulk)
                df_anomaly.loc[idx, 'Price'] = 0.01
                df_anomaly.loc[idx, 'Quantity'] = int(qty_p99 * np.random.uniform(50, 200))
        
        anomalies_injected['ml_detectable']['Unusual_Price_Qty_Ratio'] = violation_size
        print(f"  ✓ B4: Unusual price/qty ratios: {violation_size:,}")
    
    # B5. Decimal Quantities (unusual pattern - legitimate qty are integers)
    decimal_candidates = df_anomaly[
        (df_anomaly['Quantity'] > 0) &
        (~df_anomaly.index.isin(corrupted_indices))
    ].copy()
    
    if len(decimal_candidates) > 0:
        violation_size = min(int(len(df_anomaly) * 0.002), 100)
        violation_idx = np.random.choice(decimal_candidates.index, violation_size, replace=False)
        
        for idx in violation_idx:
            row_id = int(df_anomaly.loc[idx, '__row_id'])
            ground_truth['anomaly_indices'].append(row_id)
            if str(row_id) not in ground_truth['anomaly_details']:
                ground_truth['anomaly_details'][str(row_id)] = []
            ground_truth['anomaly_details'][str(row_id)].append('ml_decimal_quantity')
            corrupted_indices.add(idx)
        
        # Convert Quantity to float and add decimals
        df_anomaly['Quantity'] = df_anomaly['Quantity'].astype(float)
        df_anomaly.loc[violation_idx, 'Quantity'] = (
            df_anomaly.loc[violation_idx, 'Quantity'] + 
            np.random.uniform(0.1, 0.9, len(violation_idx))
        )
        
        anomalies_injected['ml_detectable']['Decimal_Quantity'] = violation_size
        print(f"  ✓ B5: Decimal quantities: {violation_size:,}")
    
    # B6. Suspiciously Round Numbers (e.g., Price=100.00, Qty=1000)
    round_candidates = df_anomaly[
        (df_anomaly['Price'] > 0) &
        (df_anomaly['Quantity'] > 0) &
        (~df_anomaly.index.isin(corrupted_indices))
    ].copy()
    
    if len(round_candidates) > 0:
        violation_size = min(int(len(df_anomaly) * 0.002), 100)
        violation_idx = np.random.choice(round_candidates.index, violation_size, replace=False)
        
        for idx in violation_idx:
            row_id = int(df_anomaly.loc[idx, '__row_id'])
            ground_truth['anomaly_indices'].append(row_id)
            if str(row_id) not in ground_truth['anomaly_details']:
                ground_truth['anomaly_details'][str(row_id)] = []
            ground_truth['anomaly_details'][str(row_id)].append('ml_suspicious_round')
            corrupted_indices.add(idx)
        
        # Set to suspiciously round numbers
        round_prices = [100.00, 200.00, 500.00, 1000.00]
        round_qtys = [100, 500, 1000, 5000]
        
        df_anomaly.loc[violation_idx, 'Price'] = np.random.choice(round_prices, len(violation_idx))
        df_anomaly.loc[violation_idx, 'Quantity'] = np.random.choice(round_qtys, len(violation_idx))
        
        anomalies_injected['ml_detectable']['Suspicious_Round_Numbers'] = violation_size
        print(f"  ✓ B6: Suspicious round numbers: {violation_size:,}")
    
    # ==================================================================
    # FINALIZE
    # ==================================================================
    
    ground_truth['anomaly_indices'] = sorted(list(set(ground_truth['anomaly_indices'])))
    ground_truth['total_anomalies_injected'] = len(ground_truth['anomaly_indices'])
    ground_truth['injection_summary'] = anomalies_injected
    
    total_rule = sum(anomalies_injected['rule_based'].values())
    total_ml = sum(anomalies_injected['ml_detectable'].values())
    
    # Summary
    print("\n" + "="*70)
    print("📊 INJECTION SUMMARY")
    print("="*70)
    print(f"  Original rows: {original_len:,}")
    print(f"  Total unique anomalies: {ground_truth['total_anomalies_injected']:,}")
    print(f"    ├─ Rule-based: {total_rule:,} ({total_rule/ground_truth['total_anomalies_injected']*100:.1f}%)")
    print(f"    └─ ML-detectable: {total_ml:,} ({total_ml/ground_truth['total_anomalies_injected']*100:.1f}%)")
    
    print("\n🔍 Detailed Breakdown:")
    print("\n  Rule-Based (Rules should catch):")
    for atype, count in anomalies_injected['rule_based'].items():
        print(f"    • {atype}: {count:,}")
    
    print("\n  ML-Detectable (ML should catch):")
    for atype, count in anomalies_injected['ml_detectable'].items():
        print(f"    • {atype}: {count:,}")
    
    # Remove __row_id
    df_anomaly = df_anomaly.drop(columns=['__row_id'])
    
    return df_anomaly, ground_truth


def main():
    """Main execution"""
    
    print("\n" + "="*70)
    print("🚀 ANOMALY INJECTION v4: PERCENTILE-BASED TRUE OUTLIERS")
    print("="*70)
    
    # Load data from S3
    print(f"\n📂 Loading from S3: s3://{BUCKET_NAME}/{S3_CLEAN_KEY}")
    try:
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=S3_CLEAN_KEY)
        df = pd.read_csv(BytesIO(response['Body'].read()))
        df.columns = df.columns.str.replace(' ', '')
        print(f"✓ Loaded {len(df):,} rows")
    except Exception as e:
        print(f"❌ Failed to load clean data from S3: {e}")
        return
    
    # Inject
    df_anomalous, ground_truth = inject_anomalies(df)
    
    # Save locally
    print(f"\n💾 Saving: {OUTPUT_FILE}")
    df_anomalous.to_csv(OUTPUT_FILE, index=False)
    print(f"✓ Saved")
    
    print(f"\n💾 Saving: {GROUND_TRUTH_FILE}")
    with open(GROUND_TRUTH_FILE, 'w') as f:
        json.dump(ground_truth, f, indent=2)
    print(f"✓ Saved")
    
    # Upload to S3
    print(f"\n☁️  Uploading to S3...")
    try:
        s3_client.upload_file(OUTPUT_FILE, BUCKET_NAME, S3_UPLOAD_KEY)
        print(f"✓ Data: s3://{BUCKET_NAME}/{S3_UPLOAD_KEY}")
        
        s3_client.upload_file(GROUND_TRUTH_FILE, BUCKET_NAME, S3_GROUND_TRUTH_KEY)
        print(f"✓ Ground truth: s3://{BUCKET_NAME}/{S3_GROUND_TRUTH_KEY}")
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        return
    
    # Expected results
    total_rule = sum(ground_truth['injection_summary']['rule_based'].values())
    total_ml = sum(ground_truth['injection_summary']['ml_detectable'].values())
    total = ground_truth['total_anomalies_injected']
    
    print("\n" + "="*70)
    print("🎯 EXPECTED RESULTS")
    print("="*70)
    print(f"\nRules-Only:")
    print(f"  Should catch: ~{total_rule} anomalies")
    print(f"  Expected Recall: ~{total_rule/total*100:.0f}%")
    
    print(f"\nML-Only:")
    print(f"  Should catch: ~{total_ml} anomalies")
    print(f"  Expected Recall: ~{total_ml/total*100:.0f}%")
    
    print(f"\nHybrid:")
    print(f"  Should catch: ~{total} anomalies")
    print(f"  Expected Recall: ~95-100%")
    print(f"  Expected F1: BEST! 🎉")
    
    print("\n" + "="*70)
    print("✨ NEXT STEPS")
    print("="*70)
    print("1. Wait for pipeline to complete")
    print("2. Run: python evaluate_hybrid_corrected.py")
    print("3. Verify: Hybrid > Rules and Hybrid > ML")


if __name__ == "__main__":
    main()