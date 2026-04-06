"""
Isolation Forest Training Pipeline
Trains anomaly detection model on clean retail data
"""

import pandas as pd
import numpy as np
import boto3
import pickle
import json
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import LabelEncoder
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# Configuration
CLEAN_DATA_FILE = '../online_retail_II.csv'  # Original clean CSV
MODEL_OUTPUT_FILE = 'isolation_forest_model.pkl'
FEATURE_METADATA_FILE = 'feature_metadata.json'
S3_BUCKET = 'datasourcebucket1109'
S3_MODEL_KEY = 'models/isolation_forest_model.pkl'
S3_METADATA_KEY = 'models/feature_metadata.json'

# Model parameters
CONTAMINATION = 0.02  # 2% expected anomalies
RANDOM_STATE = 42
N_ESTIMATORS = 100

s3_client = boto3.client('s3')


def load_and_clean_data(file_path):
    """Load CSV and apply basic cleaning"""
    print(f"\n📂 Loading data from: {file_path}")
    
    df = pd.read_csv(file_path)
    
    # Clean column names (remove spaces)
    if ' ' in df.columns[0]:
        df.columns = df.columns.str.replace(' ', '')
    
    print(f"✓ Loaded {len(df):,} rows")
    
    # Basic cleaning (same as Lambda)
    df['StockCode'] = df['StockCode'].astype(str).str.strip().str.upper()
    df['Invoice'] = df['Invoice'].astype(str).str.strip().str.upper()
    df['Description'] = df['Description'].astype(str).str.strip()
    
    # Convert InvoiceDate to datetime
    df['InvoiceDate'] = pd.to_datetime(df['InvoiceDate'])
    
    print(f"✓ Data cleaned")
    
    return df


def engineer_features(df, fit=True, label_encoders=None):
    """
    Feature engineering for Isolation Forest
    
    Args:
        df: Input dataframe
        fit: If True, fit label encoders. If False, use provided encoders.
        label_encoders: Pre-fitted encoders (for inference)
    
    Returns:
        features_df: DataFrame with engineered features
        label_encoders: Fitted encoders (if fit=True)
    """
    print("\n🔧 Engineering features...")
    
    df_features = df.copy()
    
    # Initialize label_encoders if needed
    if fit:
        label_encoders = {}
    elif label_encoders is None:
        label_encoders = {}
    
    # ==========================================
    # NUMERICAL FEATURES
    # ==========================================
    
    # Basic numerical
    df_features['Price_clean'] = pd.to_numeric(df_features['Price'], errors='coerce').fillna(0)
    df_features['Quantity_clean'] = pd.to_numeric(df_features['Quantity'], errors='coerce').fillna(0)
    
    # Derived numerical
    df_features['TotalAmount'] = df_features['Price_clean'] * df_features['Quantity_clean']
    df_features['AbsQuantity'] = df_features['Quantity_clean'].abs()
    df_features['AbsPrice'] = df_features['Price_clean'].abs()
    
    # ==========================================
    # TEMPORAL FEATURES
    # ==========================================
    
    df_features['Hour'] = df_features['InvoiceDate'].dt.hour
    df_features['DayOfWeek'] = df_features['InvoiceDate'].dt.dayofweek  # 0=Monday, 6=Sunday
    df_features['Month'] = df_features['InvoiceDate'].dt.month
    df_features['DayOfMonth'] = df_features['InvoiceDate'].dt.day
    df_features['IsWeekend'] = (df_features['DayOfWeek'] >= 5).astype(int)  # Saturday=5, Sunday=6
    
    # ==========================================
    # CATEGORICAL FEATURES (ENCODED)
    # ==========================================
    
    # IsCancellation (binary)
    df_features['IsCancellation'] = df_features['Invoice'].str.startswith('C').astype(int)
    
    # Price sign
    df_features['PriceSign'] = np.where(df_features['Price_clean'] > 0, 1,
                                        np.where(df_features['Price_clean'] < 0, -1, 0))
    df_features['QuantitySign'] = np.where(df_features['Quantity_clean'] > 0, 1,
                                           np.where(df_features['Quantity_clean'] < 0, -1, 0))
    
    # StockCode frequency encoding (how common is this stock code)
    if fit:
        stockcode_freq = df_features['StockCode'].value_counts(normalize=True).to_dict()
        df_features['StockCode_freq'] = df_features['StockCode'].map(stockcode_freq).fillna(0)
        label_encoders['stockcode_freq'] = stockcode_freq
    else:
        # Use pre-computed frequencies from training
        stockcode_freq = label_encoders.get('stockcode_freq', {})
        df_features['StockCode_freq'] = df_features['StockCode'].map(stockcode_freq).fillna(0)
    
    # Country encoding (one-hot for top 10, "Other" for rest)
    if fit:
        top_countries = df_features['Country'].value_counts().head(10).index.tolist()
        label_encoders['top_countries'] = top_countries
    else:
        top_countries = label_encoders.get('top_countries', [])
    
    for country in top_countries:
        df_features[f'Country_{country}'] = (df_features['Country'] == country).astype(int)
    df_features['Country_Other'] = (~df_features['Country'].isin(top_countries)).astype(int)
    
    # ==========================================
    # SELECT FINAL FEATURES
    # ==========================================
    
    feature_columns = [
        # Numerical
        'Price_clean', 'Quantity_clean', 'TotalAmount', 'AbsQuantity', 'AbsPrice',
        # Temporal
        'Hour', 'DayOfWeek', 'Month', 'DayOfMonth', 'IsWeekend',
        # Categorical
        'IsCancellation', 'PriceSign', 'QuantitySign', 'StockCode_freq',
        # Country one-hot
    ] + [f'Country_{c}' for c in top_countries] + ['Country_Other']
    
    features_df = df_features[feature_columns].copy()
    
    # Handle any remaining NaN values
    features_df = features_df.fillna(0)
    
    print(f"✓ Engineered {len(feature_columns)} features")
    print(f"  Feature list: {feature_columns[:5]}... (+{len(feature_columns)-5} more)")
    
    if fit:
        # Store metadata for inference
        metadata = {
            'feature_columns': feature_columns,
            'top_countries': top_countries,
            'stockcode_freq': stockcode_freq
        }
        return features_df, metadata
    else:
        return features_df


def train_isolation_forest(X):
    """Train Isolation Forest model"""
    print(f"\n🤖 Training Isolation Forest...")
    print(f"  Contamination: {CONTAMINATION}")
    print(f"  N_estimators: {N_ESTIMATORS}")
    print(f"  Random state: {RANDOM_STATE}")
    
    model = IsolationForest(
        contamination=CONTAMINATION,
        n_estimators=N_ESTIMATORS,
        random_state=RANDOM_STATE,
        n_jobs=-1,  # Use all CPU cores
        verbose=0
    )
    
    model.fit(X)
    
    print(f"✓ Model trained on {len(X):,} samples")
    
    # Get anomaly scores for training data (for analysis)
    scores = model.decision_function(X)
    predictions = model.predict(X)
    
    n_anomalies = (predictions == -1).sum()
    print(f"✓ Detected {n_anomalies:,} anomalies in training data ({n_anomalies/len(X)*100:.2f}%)")
    
    return model, scores, predictions


def save_model_and_metadata(model, metadata):
    """Save model and metadata locally and to S3"""
    print(f"\n💾 Saving model and metadata...")
    
    # Save model locally
    with open(MODEL_OUTPUT_FILE, 'wb') as f:
        pickle.dump(model, f)
    print(f"✓ Model saved locally: {MODEL_OUTPUT_FILE}")
    
    # Save metadata locally
    with open(FEATURE_METADATA_FILE, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"✓ Metadata saved locally: {FEATURE_METADATA_FILE}")
    
    # Upload to S3
    try:
        # Upload model
        s3_client.upload_file(MODEL_OUTPUT_FILE, S3_BUCKET, S3_MODEL_KEY)
        print(f"✓ Model uploaded to S3: s3://{S3_BUCKET}/{S3_MODEL_KEY}")
        
        # Upload metadata
        s3_client.upload_file(FEATURE_METADATA_FILE, S3_BUCKET, S3_METADATA_KEY)
        print(f"✓ Metadata uploaded to S3: s3://{S3_BUCKET}/{S3_METADATA_KEY}")
        
    except Exception as e:
        print(f"⚠ S3 upload failed: {e}")
        print(f"  Model and metadata are saved locally. Upload manually if needed.")


def analyze_model(model, X, feature_names, df_original):
    """Analyze model performance and feature importance"""
    print(f"\n📊 Model Analysis...")
    
    # Get predictions
    predictions = model.predict(X)
    scores = model.decision_function(X)
    
    # Anomaly statistics
    n_normal = (predictions == 1).sum()
    n_anomalies = (predictions == -1).sum()
    
    print(f"\n  Training set predictions:")
    print(f"    Normal: {n_normal:,} ({n_normal/len(X)*100:.1f}%)")
    print(f"    Anomalies: {n_anomalies:,} ({n_anomalies/len(X)*100:.1f}%)")
    
    # Score distribution
    print(f"\n  Anomaly score distribution:")
    print(f"    Min: {scores.min():.4f}")
    print(f"    25th percentile: {np.percentile(scores, 25):.4f}")
    print(f"    Median: {np.median(scores):.4f}")
    print(f"    75th percentile: {np.percentile(scores, 75):.4f}")
    print(f"    Max: {scores.max():.4f}")
    
    # Feature statistics
    print(f"\n  Feature value ranges:")
    for i, feat in enumerate(feature_names[:5]):  # Show first 5
        print(f"    {feat}: [{X[feat].min():.2f}, {X[feat].max():.2f}]")
    
    # Sample anomalies
    anomaly_indices = np.where(predictions == -1)[0][:5]
    if len(anomaly_indices) > 0:
        print(f"\n  Sample detected anomalies (first 5):")
        for idx in anomaly_indices:
            row = df_original.iloc[idx]
            print(f"    Row {idx}: Invoice={row['Invoice']}, Qty={row['Quantity']}, "
                  f"Price={row['Price']}, StockCode={row['StockCode']}")


def main():
    """Main training pipeline"""
    print("\n" + "="*70)
    print("🚀 ISOLATION FOREST TRAINING PIPELINE")
    print("="*70)
    
    # 1. Load and clean data
    df = load_and_clean_data(CLEAN_DATA_FILE)
    
    # 2. Engineer features
    X, metadata = engineer_features(df, fit=True)
    
    # 3. Train model
    model, scores, predictions = train_isolation_forest(X)
    
    # 4. Analyze model
    analyze_model(model, X, metadata['feature_columns'], df)
    
    # 5. Save model and metadata
    save_model_and_metadata(model, metadata)
    
    # 6. Summary
    print("\n" + "="*70)
    print("✅ TRAINING COMPLETE")
    print("="*70)
    print(f"\n📦 Outputs:")
    print(f"  Local model: {MODEL_OUTPUT_FILE}")
    print(f"  Local metadata: {FEATURE_METADATA_FILE}")
    print(f"  S3 model: s3://{S3_BUCKET}/{S3_MODEL_KEY}")
    print(f"  S3 metadata: s3://{S3_BUCKET}/{S3_METADATA_KEY}")
    
    print(f"\n🎯 Model Configuration:")
    print(f"  Contamination: {CONTAMINATION}")
    print(f"  Features: {len(metadata['feature_columns'])}")
    print(f"  Training samples: {len(X):,}")
    
    print(f"\n🚀 Next Steps:")
    print(f"  1. Deploy ML Lambda function")
    print(f"  2. Test on anomalous data")
    print(f"  3. Run hybrid evaluation")


if __name__ == "__main__":
    main()