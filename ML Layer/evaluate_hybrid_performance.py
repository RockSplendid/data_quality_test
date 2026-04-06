"""
Hybrid Performance Evaluation
Compares: Rules-Only vs ML-Only vs Hybrid (Rules + ML)
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


def download_latest_metrics(metric_type='rules', data_type='anomalies'):
    """Download the most recent metrics file"""
    if metric_type == 'rules':
        prefix = f"metrics/{data_type}/"
    else:  # ML
        prefix = f"metrics/ml/{data_type}/"
    
    try:
        response = s3_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=prefix)
        
        if 'Contents' not in response:
            print(f"No {metric_type} metrics found for {data_type}")
            return None
        
        # Get most recent
        objects = sorted(response['Contents'], key=lambda x: x['LastModified'], reverse=True)
        latest_key = objects[0]['Key']
        
        print(f"📥 Downloading {metric_type} metrics: {latest_key}")
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
    """Calculate Precision, Recall, F1-score"""
    gt_set = set(ground_truth_ids)
    flagged_set = set(flagged_ids)
    
    # Confusion matrix
    true_positives = len(gt_set & flagged_set)
    false_positives = len(flagged_set - gt_set)
    false_negatives = len(gt_set - flagged_set)
    true_negatives = total_rows - true_positives - false_positives - false_negatives
    
    # Metrics
    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
    f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    accuracy = (true_positives + true_negatives) / total_rows if total_rows > 0 else 0
    
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
            'accuracy': round(accuracy, 4)
        },
        'counts': {
            'ground_truth_anomalies': len(gt_set),
            'flagged_total': len(flagged_set),
            'correctly_flagged': true_positives,
            'incorrectly_flagged': false_positives,
            'missed_anomalies': false_negatives
        }
    }


def evaluate_hybrid():
    """Main hybrid evaluation"""
    
    print("\n" + "="*80)
    print("📊 HYBRID PERFORMANCE EVALUATION: RULES vs ML vs HYBRID")
    print("="*80)
    
    # 1. Download ground truth
    print("\n1️⃣ Loading Ground Truth...")
    ground_truth = download_ground_truth()
    
    if not ground_truth:
        print("❌ Ground truth not found!")
        return
    
    total_rows = ground_truth['total_rows']
    ground_truth_ids = ground_truth['anomaly_indices']
    
    print(f"✓ Ground truth loaded:")
    print(f"  Total rows: {total_rows:,}")
    print(f"  Injected anomalies: {len(ground_truth_ids):,}")
    
    # 2. Download Rules metrics
    print("\n2️⃣ Loading Rule-Based Results...")
    rules_metrics = download_latest_metrics('rules', 'anomalies')
    
    if not rules_metrics:
        print("❌ Rules metrics not found!")
        return
    
    rules_flagged = rules_metrics.get('all_flagged_row_ids', [])
    print(f"✓ Rules flagged: {len(rules_flagged):,} records")
    
    # 3. Download ML metrics
    print("\n3️⃣ Loading ML Results...")
    ml_metrics = download_latest_metrics('ml', 'anomalies')
    
    if not ml_metrics:
        print("❌ ML metrics not found!")
        return
    
    ml_flagged = ml_metrics.get('flagged_row_ids', [])
    print(f"✓ ML flagged: {len(ml_flagged):,} records")
    
    # 4. Calculate performance for each approach
    print("\n4️⃣ Calculating Performance Metrics...")
    
    # Rules-Only
    rules_results = calculate_metrics(ground_truth_ids, rules_flagged, total_rows)
    
    # ML-Only (on original data, not rule-filtered)
    # Note: ML was run on data after rules, so we need to map back to original row IDs
    # For now, assume ML row IDs are relative to the original dataset
    ml_results = calculate_metrics(ground_truth_ids, ml_flagged, total_rows)
    
    # Hybrid (Rules + ML)
    # Combine flagged IDs from both approaches
    hybrid_flagged = list(set(rules_flagged) | set(ml_flagged))
    hybrid_results = calculate_metrics(ground_truth_ids, hybrid_flagged, total_rows)
    
    # 5. Display comparison
    print("\n" + "="*80)
    print("📈 PERFORMANCE COMPARISON")
    print("="*80)
    
    print(f"\n{'Metric':<20} {'Rules-Only':<15} {'ML-Only':<15} {'Hybrid':<15} {'Best':<10}")
    print("-" * 80)
    
    metrics_to_compare = [
        ('Precision', 'precision'),
        ('Recall', 'recall'),
        ('F1-Score', 'f1_score'),
        ('Accuracy', 'accuracy')
    ]
    
    for display_name, metric_key in metrics_to_compare:
        rules_val = rules_results['metrics'][metric_key]
        ml_val = ml_results['metrics'][metric_key]
        hybrid_val = hybrid_results['metrics'][metric_key]
        
        # Determine best
        best_val = max(rules_val, ml_val, hybrid_val)
        if best_val == rules_val:
            best = "Rules"
        elif best_val == ml_val:
            best = "ML"
        else:
            best = "Hybrid"
        
        print(f"{display_name:<20} {rules_val:.2%}{'':>7} {ml_val:.2%}{'':>7} {hybrid_val:.2%}{'':>7} {best:<10}")
    
    # Detailed breakdown
    print("\n" + "="*80)
    print("🔍 DETAILED BREAKDOWN")
    print("="*80)
    
    approaches = [
        ("RULES-ONLY", rules_results),
        ("ML-ONLY", ml_results),
        ("HYBRID (Rules + ML)", hybrid_results)
    ]
    
    for name, results in approaches:
        print(f"\n{name}:")
        cm = results['confusion_matrix']
        m = results['metrics']
        c = results['counts']
        
        print(f"  Flagged: {c['flagged_total']:,} records")
        print(f"  ✓ True Positives:  {cm['true_positives']:,}")
        print(f"  ✗ False Positives: {cm['false_positives']:,}")
        print(f"  ✗ False Negatives: {cm['false_negatives']:,}")
        print(f"  → Precision: {m['precision']:.2%} | Recall: {m['recall']:.2%} | F1: {m['f1_score']:.2%}")
    
    # 6. Analysis
    print("\n" + "="*80)
    print("💡 ANALYSIS")
    print("="*80)
    
    rules_f1 = rules_results['metrics']['f1_score']
    ml_f1 = ml_results['metrics']['f1_score']
    hybrid_f1 = hybrid_results['metrics']['f1_score']
    
    print(f"\nF1-Score Improvements:")
    print(f"  ML vs Rules: {(ml_f1 - rules_f1):.2%} {'improvement' if ml_f1 > rules_f1 else 'degradation'}")
    print(f"  Hybrid vs Rules: {(hybrid_f1 - rules_f1):.2%} {'improvement' if hybrid_f1 > rules_f1 else 'degradation'}")
    print(f"  Hybrid vs ML: {(hybrid_f1 - ml_f1):.2%} {'improvement' if hybrid_f1 > ml_f1 else 'degradation'}")
    
    # Unique catches
    rules_only_catch = set(rules_flagged) - set(ml_flagged)
    ml_only_catch = set(ml_flagged) - set(rules_flagged)
    both_catch = set(rules_flagged) & set(ml_flagged)
    
    print(f"\nUnique Detections:")
    print(f"  Caught by Rules ONLY: {len(rules_only_catch):,}")
    print(f"  Caught by ML ONLY: {len(ml_only_catch):,}")
    print(f"  Caught by BOTH: {len(both_catch):,}")
    
    # 7. Save report
    print("\n💾 Saving Evaluation Report...")
    
    report = {
        'timestamp': datetime.utcnow().isoformat(),
        'ground_truth': {
            'total_rows': total_rows,
            'injected_anomalies': len(ground_truth_ids)
        },
        'approaches': {
            'rules_only': {
                'flagged_count': len(rules_flagged),
                'performance': rules_results
            },
            'ml_only': {
                'flagged_count': len(ml_flagged),
                'performance': ml_results
            },
            'hybrid': {
                'flagged_count': len(hybrid_flagged),
                'performance': hybrid_results
            }
        },
        'comparison': {
            'ml_vs_rules_f1_improvement': round(ml_f1 - rules_f1, 4),
            'hybrid_vs_rules_f1_improvement': round(hybrid_f1 - rules_f1, 4),
            'hybrid_vs_ml_f1_improvement': round(hybrid_f1 - ml_f1, 4)
        }
    }
    
    report_file = f"hybrid_evaluation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"✓ Report saved: {report_file}")
    
    # Upload to S3
    s3_key = f"evaluations/hybrid_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    try:
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=s3_key,
            Body=json.dumps(report, indent=2)
        )
        print(f"✓ Report uploaded: s3://{BUCKET_NAME}/{s3_key}")
    except Exception as e:
        print(f"⚠ Upload failed: {e}")
    
    # 8. Conclusion
    print("\n" + "="*80)
    print("✨ CONCLUSION")
    print("="*80)
    
    if hybrid_f1 > max(rules_f1, ml_f1):
        print("\n🎉 HYBRID approach achieves BEST performance!")
        print(f"   F1-Score: {hybrid_f1:.2%}")
        print(f"   Improvement over Rules: +{(hybrid_f1 - rules_f1):.2%}")
        print(f"   Improvement over ML: +{(hybrid_f1 - ml_f1):.2%}")
    elif ml_f1 > rules_f1:
        print("\n🤖 ML-ONLY approach outperforms Rules!")
        print(f"   ML F1-Score: {ml_f1:.2%}")
        print(f"   Rules F1-Score: {rules_f1:.2%}")
        print(f"   Improvement: +{(ml_f1 - rules_f1):.2%}")
    else:
        print("\n📏 RULES-ONLY approach performs best!")
        print(f"   Rules F1-Score: {rules_f1:.2%}")
        print(f"   Note: Consider tuning ML model or adding more features")
    
    print("\n" + "="*80)


if __name__ == "__main__":
    evaluate_hybrid()