"""
Performance Evaluation Script
Calculates Precision, Recall, F1-score for rule-based quality checks
Compares flagged rows vs ground truth
"""

import json
import boto3
from datetime import datetime

BUCKET_NAME = 'datasourcebucket1109'
s3_client = boto3.client('s3')


def download_json_from_s3(key):
    """Download and parse JSON file from S3"""
    try:
        obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=key)
        return json.loads(obj['Body'].read().decode('utf-8'))
    except Exception as e:
        print(f"Error downloading {key}: {e}")
        return None


def download_latest_metrics(data_type='anomalies'):
    """Download the most recent metrics file"""
    prefix = f"metrics/{data_type}/"
    
    try:
        response = s3_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=prefix)
        
        if 'Contents' not in response:
            print(f"No metrics found for {data_type}")
            return None
        
        # Get most recent
        objects = sorted(response['Contents'], key=lambda x: x['LastModified'], reverse=True)
        latest_key = objects[0]['Key']
        
        print(f"📥 Downloading metrics: {latest_key}")
        return download_json_from_s3(latest_key)
        
    except Exception as e:
        print(f"Error: {e}")
        return None


def download_ground_truth():
    """Download ground truth file"""
    key = 'RawZone-Anomalies/online_retail_II_ground_truth.json'
    print(f"📥 Downloading ground truth: {key}")
    return download_json_from_s3(key)


def calculate_metrics(ground_truth_ids, flagged_ids, total_rows):
    """
    Calculate Precision, Recall, F1-score
    
    Args:
        ground_truth_ids: List of row IDs that are truly anomalous
        flagged_ids: List of row IDs flagged by rules
        total_rows: Total number of rows in dataset
    
    Returns:
        Dictionary with P/R/F1 and confusion matrix
    """
    # Convert to sets for efficient operations
    gt_set = set(ground_truth_ids)
    flagged_set = set(flagged_ids)
    
    # Confusion matrix
    true_positives = len(gt_set & flagged_set)  # Correctly flagged anomalies
    false_positives = len(flagged_set - gt_set)  # Incorrectly flagged clean rows
    false_negatives = len(gt_set - flagged_set)  # Missed anomalies
    true_negatives = total_rows - true_positives - false_positives - false_negatives
    
    # Metrics
    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
    f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    
    # Additional metrics
    accuracy = (true_positives + true_negatives) / total_rows if total_rows > 0 else 0
    specificity = true_negatives / (true_negatives + false_positives) if (true_negatives + false_positives) > 0 else 0
    
    return {
        'confusion_matrix': {
            'true_positives': true_positives,
            'false_positives': false_positives,
            'true_negatives': true_negatives,
            'false_negatives': false_negatives
        },
        'metrics': {
            'precision': round(precision, 4),
            'recall': round(recall, 4),
            'f1_score': round(f1_score, 4),
            'accuracy': round(accuracy, 4),
            'specificity': round(specificity, 4)
        },
        'counts': {
            'total_rows': total_rows,
            'ground_truth_anomalies': len(gt_set),
            'flagged_by_rules': len(flagged_set),
            'correctly_flagged': true_positives,
            'incorrectly_flagged': false_positives,
            'missed_anomalies': false_negatives
        }
    }


def evaluate_performance():
    """Main evaluation function"""
    
    print("\n" + "="*70)
    print("📊 PERFORMANCE EVALUATION: RULE-BASED QUALITY CHECKS")
    print("="*70)
    
    # 1. Download ground truth
    print("\n1️⃣ Loading Ground Truth...")
    ground_truth = download_ground_truth()
    
    if not ground_truth:
        print("❌ Ground truth not found!")
        print("   Run inject_anomalies_v2.py first to create ground truth.")
        return
    
    total_rows = ground_truth['total_rows']
    ground_truth_ids = ground_truth['anomaly_indices']
    
    print(f"✓ Ground truth loaded:")
    print(f"  Total rows: {total_rows:,}")
    print(f"  Injected anomalies: {len(ground_truth_ids):,}")
    
    # 2. Download latest metrics
    print("\n2️⃣ Loading Rule-Based Detection Results...")
    metrics = download_latest_metrics('anomalies')
    
    if not metrics:
        print("❌ Metrics not found!")
        print("   Process the anomalous data through Lambda first.")
        return
    
    flagged_ids = metrics.get('all_flagged_row_ids', [])
    
    print(f"✓ Metrics loaded:")
    print(f"  Flagged by rules: {len(flagged_ids):,}")
    print(f"  Processing time: {metrics['processing_time_total_sec']:.2f} sec")
    
    # 3. Calculate performance metrics
    print("\n3️⃣ Calculating Performance Metrics...")
    results = calculate_metrics(ground_truth_ids, flagged_ids, total_rows)
    
    # 4. Display results
    print("\n" + "="*70)
    print("🎯 CONFUSION MATRIX")
    print("="*70)
    cm = results['confusion_matrix']
    print(f"""
                    Predicted Positive    Predicted Negative
Actual Positive     {cm['true_positives']:>10,}          {cm['false_negatives']:>10,}
Actual Negative     {cm['false_positives']:>10,}          {cm['true_negatives']:>10,}
    """)
    
    print("\n" + "="*70)
    print("📈 PERFORMANCE METRICS")
    print("="*70)
    m = results['metrics']
    print(f"""
Precision:    {m['precision']:.2%}  (Of flagged records, {m['precision']:.1%} were truly anomalous)
Recall:       {m['recall']:.2%}  (Of all anomalies, {m['recall']:.1%} were caught)
F1-Score:     {m['f1_score']:.2%}  (Harmonic mean of Precision and Recall)
Accuracy:     {m['accuracy']:.2%}  (Overall correctness)
Specificity:  {m['specificity']:.2%}  (Of clean records, {m['specificity']:.1%} passed)
    """)
    
    print("\n" + "="*70)
    print("🔍 DETAILED BREAKDOWN")
    print("="*70)
    c = results['counts']
    print(f"""
Total rows in dataset:        {c['total_rows']:>10,}
Ground truth anomalies:       {c['ground_truth_anomalies']:>10,}
Records flagged by rules:     {c['flagged_by_rules']:>10,}

✓ Correctly flagged (TP):     {c['correctly_flagged']:>10,}
✗ Incorrectly flagged (FP):   {c['incorrectly_flagged']:>10,}
✗ Missed anomalies (FN):      {c['missed_anomalies']:>10,}
    """)
    
    # 5. Per-rule-group breakdown
    print("\n" + "="*70)
    print("📋 PER-RULE-GROUP BREAKDOWN")
    print("="*70)
    
    for group_name, group_data in metrics['rule_groups'].items():
        if group_data.get('enabled'):
            print(f"\n{group_name.upper().replace('_', ' ')}:")
            print(f"  Records removed: {group_data['records_removed']:,}")
            
            if 'rules' in group_data:
                for rule_name, rule_data in group_data['rules'].items():
                    removed = rule_data.get('removed', 0)
                    flagged_rule_ids = rule_data.get('flagged_ids', [])
                    
                    # Calculate metrics for this specific rule
                    rule_results = calculate_metrics(ground_truth_ids, flagged_rule_ids, total_rows)
                    rule_metrics = rule_results['metrics']
                    
                    print(f"    • {rule_name}: {removed:,} removed | "
                          f"P={rule_metrics['precision']:.2%} R={rule_metrics['recall']:.2%} "
                          f"F1={rule_metrics['f1_score']:.2%}")
    
    # 6. Save evaluation report
    print("\n💾 Saving Evaluation Report...")
    
    report = {
        'timestamp': datetime.utcnow().isoformat(),
        'evaluation_type': 'rule_based',
        'phase': 'phase_1_business_rules',
        'ground_truth': {
            'total_rows': total_rows,
            'injected_anomalies': len(ground_truth_ids)
        },
        'rule_based_results': {
            'flagged_count': len(flagged_ids),
            'processing_time_sec': metrics['processing_time_total_sec']
        },
        'performance_metrics': results
    }
    
    report_file = f"evaluation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"✓ Report saved: {report_file}")
    
    # 7. Upload to S3
    s3_key = f"evaluations/phase1_rules_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    try:
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=s3_key,
            Body=json.dumps(report, indent=2)
        )
        print(f"✓ Report uploaded: s3://{BUCKET_NAME}/{s3_key}")
    except Exception as e:
        print(f"⚠ Upload failed: {e}")
    
    # 8. Interpretation
    print("\n" + "="*70)
    print("💡 INTERPRETATION")
    print("="*70)
    
    if m['f1_score'] >= 0.90:
        print("✓ Excellent performance! F1-score ≥ 90%")
    elif m['f1_score'] >= 0.80:
        print("✓ Good performance. F1-score ≥ 80%")
    elif m['f1_score'] >= 0.70:
        print("⚠ Moderate performance. F1-score ≥ 70%")
    else:
        print("✗ Poor performance. F1-score < 70%")
    
    if m['precision'] < m['recall']:
        print(f"\n⚠ High false positive rate ({cm['false_positives']:,} clean records flagged)")
        print("  Rules may be too strict - consider tuning thresholds")
    elif m['recall'] < m['precision']:
        print(f"\n⚠ Missing {cm['false_negatives']:,} anomalies")
        print("  Rules may be too lenient - consider additional checks")
    
    print("\n📌 Baseline established for ML comparison!")
    print(f"   ML models should aim for F1-score > {m['f1_score']:.2%}")
    
    print("\n" + "="*70)
    print("✨ EVALUATION COMPLETE")
    print("="*70)


if __name__ == "__main__":
    evaluate_performance()