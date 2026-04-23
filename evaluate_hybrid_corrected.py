"""
CORRECTED Hybrid Performance Evaluation
Compares: Rules-Only vs Hybrid (Rules + ML Sequential)
Removes ML-Only comparison (not a fair comparison since ML sees filtered data)
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
    """
    Main evaluation: Compare Rules-Only vs Hybrid (Sequential)
    
    NOTE: We don't compare "ML-Only" because ML runs on rule-filtered data,
    not the original dataset. It would be an unfair comparison.
    
    The goal is to show: Hybrid (Rules + ML) > Rules-Only
    """
    
    print("\n" + "="*80)
    print("📊 PERFORMANCE EVALUATION: RULES vs HYBRID (SEQUENTIAL)")
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
    
    # 3. Download ML metrics (optional - only for hybrid)
    print("\n3️⃣ Loading ML Results...")
    ml_metrics = download_latest_metrics('ml', 'anomalies')
    
    if not ml_metrics:
        print("⚠️  ML metrics not found (ML Lambda hasn't run yet)")
        print("   Proceeding with Rules-Only evaluation...")
        ml_flagged = []
    else:
        ml_flagged = ml_metrics.get('flagged_row_ids', [])
        print(f"✓ ML flagged: {len(ml_flagged):,} additional records")
    
    # 4. Calculate performance
    print("\n4️⃣ Calculating Performance Metrics...")
    
    # Rules-Only (baseline)
    rules_results = calculate_metrics(ground_truth_ids, rules_flagged, total_rows)
    
    # Hybrid (Sequential: Rules + ML)
    # In sequential pipeline: rows flagged by Rules never reach ML
    # So NO overlap is possible, union = sum
    hybrid_flagged = list(set(rules_flagged) | set(ml_flagged))
    
    # Sanity check: verify no overlap
    overlap = set(rules_flagged) & set(ml_flagged)
    if overlap:
        print(f"⚠️  WARNING: Found {len(overlap)} overlapping IDs!")
        print(f"   This indicates a bug in row ID preservation!")
        print(f"   Sample overlap: {list(overlap)[:5]}")
    
    hybrid_results = calculate_metrics(ground_truth_ids, hybrid_flagged, total_rows)
    
    # 5. Display comparison
    print("\n" + "="*80)
    print("📈 PERFORMANCE COMPARISON")
    print("="*80)
    
    print(f"\n{'Metric':<20} {'Rules-Only':<15} {'Hybrid':<15} {'Improvement':<15}")
    print("-" * 65)
    
    metrics_to_compare = [
        ('Precision', 'precision'),
        ('Recall', 'recall'),
        ('F1-Score', 'f1_score'),
    ]
    
    for display_name, metric_key in metrics_to_compare:
        rules_val = rules_results['metrics'][metric_key]
        hybrid_val = hybrid_results['metrics'][metric_key]
        improvement = hybrid_val - rules_val
        
        improvement_str = f"+{improvement:.2%}" if improvement > 0 else f"{improvement:.2%}"
        
        print(f"{display_name:<20} {rules_val:.2%}{'':>7} {hybrid_val:.2%}{'':>7} {improvement_str:<15}")
    
    # 6. Detailed breakdown
    print("\n" + "="*80)
    print("🔍 DETAILED BREAKDOWN")
    print("="*80)
    
    print(f"\nRULES-ONLY (Baseline):")
    cm = rules_results['confusion_matrix']
    m = rules_results['metrics']
    c = rules_results['counts']
    
    print(f"  Flagged: {c['flagged_total']:,} records")
    print(f"  ✓ True Positives:  {cm['true_positives']:,} (correctly flagged anomalies)")
    print(f"  ✗ False Positives: {cm['false_positives']:,} (incorrectly flagged clean rows)")
    print(f"  ✗ False Negatives: {cm['false_negatives']:,} (missed anomalies)")
    print(f"  → Precision: {m['precision']:.2%} | Recall: {m['recall']:.2%} | F1: {m['f1_score']:.2%}")
    
    print(f"\nHYBRID (Rules + ML Sequential):")
    cm_h = hybrid_results['confusion_matrix']
    m_h = hybrid_results['metrics']
    c_h = hybrid_results['counts']
    
    print(f"  Flagged: {c_h['flagged_total']:,} records")
    print(f"    ├─ By Rules: {len(rules_flagged):,}")
    print(f"    └─ By ML (additional): {len(ml_flagged):,}")
    print(f"  ✓ True Positives:  {cm_h['true_positives']:,} (correctly flagged anomalies)")
    print(f"  ✗ False Positives: {cm_h['false_positives']:,} (incorrectly flagged clean rows)")
    print(f"  ✗ False Negatives: {cm_h['false_negatives']:,} (missed anomalies)")
    print(f"  → Precision: {m_h['precision']:.2%} | Recall: {m_h['recall']:.2%} | F1: {m_h['f1_score']:.2%}")
    
    # 7. Analysis
    print("\n" + "="*80)
    print("💡 ANALYSIS")
    print("="*80)
    
    f1_improvement = m_h['f1_score'] - m['f1_score']
    
    if f1_improvement > 0:
        print(f"\n✅ HYBRID WINS!")
        print(f"   F1 improvement: +{f1_improvement:.2%}")
        print(f"   ML caught {cm_h['true_positives'] - cm['true_positives']} additional anomalies")
        
        if cm_h['false_positives'] < cm['false_positives']:
            print(f"   Bonus: Reduced false positives by {cm['false_positives'] - cm_h['false_positives']}")
    
    elif f1_improvement == 0:
        print(f"\n➡️  TIE: ML didn't improve performance")
        print(f"   ML may need tuning (adjust contamination parameter)")
    
    else:
        print(f"\n⚠️  RULES BETTER: Hybrid performed worse!")
        print(f"   F1 degradation: {f1_improvement:.2%}")
        print(f"   ML may be flagging too many false positives")
        print(f"   Consider: Lower contamination parameter or add more features")
    
    # Unique catches
    if ml_flagged:
        ml_only_catch = set(ml_flagged) - set(rules_flagged)
        if ml_only_catch:
            ml_tp = len(set(ground_truth_ids) & ml_only_catch)
            ml_fp = len(ml_only_catch - set(ground_truth_ids))
            print(f"\nML Unique Detections:")
            print(f"  Total caught by ML (not by Rules): {len(ml_only_catch)}")
            print(f"  ✓ True anomalies: {ml_tp}")
            print(f"  ✗ False positives: {ml_fp}")
    
    # 8. Investigation hints
    if m['precision'] < 0.5:
        print("\n" + "="*80)
        print("⚠️  LOW PRECISION WARNING!")
        print("="*80)
        print(f"\nRules precision is {m['precision']:.1%} - this is very low!")
        print("\nPossible causes:")
        print("  1. Ground truth row IDs don't match flagged row IDs")
        print("  2. Injection script recorded wrong row IDs")
        print("  3. Row ID preservation broken in pipeline")
        print("  4. Loading wrong metrics file (clean instead of anomalies)")
        print("  5. Rules are too strict and flagging legitimate operational data")
        print("\n👉 Run debugging steps from EVALUATION_FIX_AND_DEBUG.md")
    
    # 9. Save report
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
            'hybrid': {
                'flagged_count': len(hybrid_flagged),
                'rules_contribution': len(rules_flagged),
                'ml_contribution': len(ml_flagged),
                'performance': hybrid_results
            }
        },
        'comparison': {
            'f1_improvement': round(f1_improvement, 4),
            'precision_improvement': round(m_h['precision'] - m['precision'], 4),
            'recall_improvement': round(m_h['recall'] - m['recall'], 4),
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
    
    # 10. Conclusion
    print("\n" + "="*80)
    print("✨ CONCLUSION")
    print("="*80)
    
    if f1_improvement > 0:
        print(f"\n🎉 SUCCESS! Hybrid approach improves F1-Score by {f1_improvement:.2%}")
        print(f"   Rules F1: {m['f1_score']:.2%}")
        print(f"   Hybrid F1: {m_h['f1_score']:.2%}")
    elif f1_improvement == 0:
        print(f"\n📊 Hybrid approach matches Rules performance (F1: {m['f1_score']:.2%})")
        print(f"   ML needs tuning to add value")
    else:
        print(f"\n⚠️  Hybrid approach underperforms Rules")
        print(f"   Consider tuning ML model or revisiting features")
    
    print("\n" + "="*80)


if __name__ == "__main__":
    evaluate_hybrid()