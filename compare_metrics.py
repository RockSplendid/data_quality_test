"""
Metrics Comparison Script
Compares rule-based quality check results: Clean vs Anomalous data
"""

import json
import boto3
from datetime import datetime
import pandas as pd

BUCKET_NAME = 'datasourcebucket1109'
s3_client = boto3.client('s3')


def download_latest_metrics(data_type='clean'):
    """Download the most recent metrics file for a data type"""
    prefix = f"metrics/{data_type}/"
    
    try:
        response = s3_client.list_objects_v2(
            Bucket=BUCKET_NAME,
            Prefix=prefix
        )
        
        if 'Contents' not in response:
            print(f"No metrics found for {data_type}")
            return None
        
        # Sort by last modified, get most recent
        objects = sorted(response['Contents'], key=lambda x: x['LastModified'], reverse=True)
        latest_key = objects[0]['Key']
        
        print(f"📥 Downloading: {latest_key}")
        
        obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=latest_key)
        metrics = json.loads(obj['Body'].read().decode('utf-8'))
        
        return metrics
        
    except Exception as e:
        print(f"Error downloading metrics: {e}")
        return None


def compare_metrics(clean_metrics, anomaly_metrics):
    """Compare metrics between clean and anomalous data"""
    
    print("\n" + "="*70)
    print("📊 METRICS COMPARISON: CLEAN vs ANOMALOUS DATA")
    print("="*70)
    
    # Overall comparison
    print("\n🔍 OVERALL STATISTICS")
    print("-"*70)
    
    comparison_data = {
        'Metric': [],
        'Clean Data': [],
        'Anomalous Data': [],
        'Difference': []
    }
    
    # Initial records
    clean_initial = clean_metrics['initial_record_count']
    anom_initial = anomaly_metrics['initial_record_count']
    comparison_data['Metric'].append('Initial Records')
    comparison_data['Clean Data'].append(f"{clean_initial:,}")
    comparison_data['Anomalous Data'].append(f"{anom_initial:,}")
    comparison_data['Difference'].append(f"+{anom_initial - clean_initial:,}")
    
    # Final records
    clean_final = clean_metrics['final_record_count']
    anom_final = anomaly_metrics['final_record_count']
    comparison_data['Metric'].append('Final Records')
    comparison_data['Clean Data'].append(f"{clean_final:,}")
    comparison_data['Anomalous Data'].append(f"{anom_final:,}")
    comparison_data['Difference'].append(f"{anom_final - clean_final:,}")
    
    # Total removed
    clean_removed = clean_metrics['total_records_removed']
    anom_removed = anomaly_metrics['total_records_removed']
    comparison_data['Metric'].append('Total Removed')
    comparison_data['Clean Data'].append(f"{clean_removed:,}")
    comparison_data['Anomalous Data'].append(f"{anom_removed:,}")
    comparison_data['Difference'].append(f"+{anom_removed - clean_removed:,}")
    
    # Removal percentage
    clean_pct = clean_metrics['removal_percentage']
    anom_pct = anomaly_metrics['removal_percentage']
    comparison_data['Metric'].append('Removal %')
    comparison_data['Clean Data'].append(f"{clean_pct}%")
    comparison_data['Anomalous Data'].append(f"{anom_pct}%")
    comparison_data['Difference'].append(f"+{anom_pct - clean_pct:.2f}%")
    
    # Processing time
    clean_time = clean_metrics['processing_time_total_sec']
    anom_time = anomaly_metrics['processing_time_total_sec']
    comparison_data['Metric'].append('Processing Time (sec)')
    comparison_data['Clean Data'].append(f"{clean_time:.2f}")
    comparison_data['Anomalous Data'].append(f"{anom_time:.2f}")
    comparison_data['Difference'].append(f"+{anom_time - clean_time:.2f}")
    
    df_overall = pd.DataFrame(comparison_data)
    print(df_overall.to_string(index=False))
    
    # Rule group comparison
    print("\n\n🔧 RULE GROUP BREAKDOWN")
    print("-"*70)
    
    for group_name in ['basic_checks', 'business_rules']:
        if group_name in clean_metrics['rule_groups'] and group_name in anomaly_metrics['rule_groups']:
            clean_group = clean_metrics['rule_groups'][group_name]
            anom_group = anomaly_metrics['rule_groups'][group_name]
            
            if clean_group.get('enabled') and anom_group.get('enabled'):
                print(f"\n📌 {group_name.upper().replace('_', ' ')}")
                
                group_data = {
                    'Rule': [],
                    'Clean Removed': [],
                    'Anomaly Removed': [],
                    'Delta': []
                }
                
                # Group totals
                group_data['Rule'].append('TOTAL')
                group_data['Clean Removed'].append(f"{clean_group['records_removed']:,}")
                group_data['Anomaly Removed'].append(f"{anom_group['records_removed']:,}")
                group_data['Delta'].append(f"+{anom_group['records_removed'] - clean_group['records_removed']:,}")
                
                # Individual rules
                for rule_name, rule_data in clean_group.get('rules', {}).items():
                    clean_removed_rule = rule_data['removed']
                    anom_removed_rule = anom_group['rules'].get(rule_name, {}).get('removed', 0)
                    
                    group_data['Rule'].append(rule_name.replace('_', ' ').title())
                    group_data['Clean Removed'].append(f"{clean_removed_rule:,}")
                    group_data['Anomaly Removed'].append(f"{anom_removed_rule:,}")
                    group_data['Delta'].append(f"+{anom_removed_rule - clean_removed_rule:,}")
                
                df_group = pd.DataFrame(group_data)
                print(df_group.to_string(index=False))
    
    # Detection effectiveness
    print("\n\n✅ DETECTION EFFECTIVENESS")
    print("-"*70)
    
    # Calculate how many MORE anomalies were caught in anomalous data
    extra_caught = anom_removed - clean_removed
    
    print(f"\n🎯 Additional Anomalies Detected: {extra_caught:,} records")
    print(f"   (This represents the injected anomalies that were successfully caught)")
    
    # Business rules effectiveness
    if 'business_rules' in clean_metrics['rule_groups'] and 'business_rules' in anomaly_metrics['rule_groups']:
        clean_biz = clean_metrics['rule_groups']['business_rules']['records_removed']
        anom_biz = anomaly_metrics['rule_groups']['business_rules']['records_removed']
        
        print(f"\n📊 Business Rules Performance:")
        print(f"   Clean data violations: {clean_biz:,} ({(clean_biz/clean_initial*100):.2f}%)")
        print(f"   Anomalous data violations: {anom_biz:,} ({(anom_biz/anom_initial*100):.2f}%)")
        print(f"   Additional caught: {anom_biz - clean_biz:,}")
        
        print(f"\n💡 Interpretation:")
        if anom_biz > clean_biz * 1.5:
            print(f"   ✓ Business rules effectively detected injected anomalies")
        else:
            print(f"   ⚠ Business rules may need tuning or data has fewer violations than expected")


def main():
    """Main comparison function"""
    
    print("\n" + "="*70)
    print("🚀 DATA QUALITY METRICS COMPARISON TOOL")
    print("="*70)
    
    # Download metrics
    print("\n1️⃣ Downloading Clean Data Metrics...")
    clean_metrics = download_latest_metrics('clean')
    
    print("\n2️⃣ Downloading Anomalous Data Metrics...")
    anomaly_metrics = download_latest_metrics('anomalies')
    
    if not clean_metrics:
        print("\n❌ No clean data metrics found. Upload data to RawZone/ first.")
        return
    
    if not anomaly_metrics:
        print("\n❌ No anomalous data metrics found. Run inject_anomalies.py first.")
        return
    
    # Compare
    print("\n3️⃣ Comparing Metrics...")
    compare_metrics(clean_metrics, anomaly_metrics)
    
    # Save comparison report
    print("\n\n💾 Saving Comparison Report...")
    
    report_file = f"comparison_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    with open(report_file, 'w') as f:
        f.write("DATA QUALITY METRICS COMPARISON REPORT\n")
        f.write("="*70 + "\n\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n")
        f.write(f"Clean data source: {clean_metrics['source_file']}\n")
        f.write(f"Anomalous data source: {anomaly_metrics['source_file']}\n\n")
        
        f.write("SUMMARY\n")
        f.write("-"*70 + "\n")
        f.write(f"Initial Records - Clean: {clean_metrics['initial_record_count']:,}\n")
        f.write(f"Initial Records - Anomalous: {anomaly_metrics['initial_record_count']:,}\n")
        f.write(f"Final Records - Clean: {clean_metrics['final_record_count']:,}\n")
        f.write(f"Final Records - Anomalous: {anomaly_metrics['final_record_count']:,}\n")
        f.write(f"Total Removed - Clean: {clean_metrics['total_records_removed']:,} ({clean_metrics['removal_percentage']}%)\n")
        f.write(f"Total Removed - Anomalous: {anomaly_metrics['total_records_removed']:,} ({anomaly_metrics['removal_percentage']}%)\n")
        f.write(f"\nAdditional Anomalies Detected: {anomaly_metrics['total_records_removed'] - clean_metrics['total_records_removed']:,}\n")
        
        f.write("\n\nRULE GROUP DETAILS\n")
        f.write("-"*70 + "\n")
        
        for group_name in ['basic_checks', 'business_rules']:
            if group_name in clean_metrics['rule_groups'] and group_name in anomaly_metrics['rule_groups']:
                clean_group = clean_metrics['rule_groups'][group_name]
                anom_group = anomaly_metrics['rule_groups'][group_name]
                
                if clean_group.get('enabled'):
                    f.write(f"\n{group_name.upper().replace('_', ' ')}\n")
                    f.write(f"  Clean: {clean_group['records_removed']:,} removed\n")
                    f.write(f"  Anomalous: {anom_group['records_removed']:,} removed\n")
                    f.write(f"  Delta: +{anom_group['records_removed'] - clean_group['records_removed']:,}\n")
    
    print(f"✓ Report saved: {report_file}")
    
    print("\n" + "="*70)
    print("✨ COMPARISON COMPLETE")
    print("="*70)


if __name__ == "__main__":
    main()