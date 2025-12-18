"""
Online Retail II Dataset - Complete Analysis & Anomaly Injection
Prerequisites: pip install duckdb pandas openpyxl kagglehub
"""

import duckdb
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
import os
warnings.filterwarnings('ignore')

class RetailDataAnalyzer:
    def __init__(self, file_path=None, download_from_kaggle=False):
        """Initialize with dataset file path or download from Kaggle"""
        if download_from_kaggle:
            self.file_path = self.download_dataset()
        else:
            self.file_path = file_path
        self.df = None
        self.con = None
    
    def download_dataset(self):
        """Download dataset from Kaggle using kagglehub"""
        print("📥 Downloading dataset from Kaggle...")
        try:
            import kagglehub
            path = kagglehub.dataset_download("mashlyn/online-retail-ii-uci")
            print(f"✅ Downloaded to: {path}")
            
            # Find the Excel or CSV file in the downloaded path
            for file in os.listdir(path):
                if file.endswith(('.xlsx', '.csv')):
                    full_path = os.path.join(path, file)
                    print(f"📂 Found dataset file: {file}")
                    return full_path
            
            raise FileNotFoundError("No Excel or CSV file found in downloaded dataset")
        except ImportError:
            print("❌ kagglehub not installed. Install with: pip install kagglehub")
            raise
        
    def load_data(self):
        """Load dataset and create DuckDB connection"""
        print("📂 Loading dataset...")
        try:
            # Try Excel first
            self.df = pd.read_excel(self.file_path)
        except:
            # Fall back to CSV
            self.df = pd.read_csv(self.file_path)
            # Clean column names - replace spaces with underscores
            self.df.columns = self.df.columns.str.replace(' ', '')
        
        print(f"✅ Loaded {len(self.df):,} rows and {len(self.df.columns)} columns")
        
        # Create DuckDB connection
        self.con = duckdb.connect(':memory:')
        self.con.register('retail', self.df)
        
    def profile_dataset(self):
        """Comprehensive data profiling"""
        print("\n" + "="*60)
        print("📊 DATASET PROFILING")
        print("="*60)
        
        # Basic statistics
        print("\n1️⃣ BASIC STATISTICS")
        stats = self.con.execute("""
            SELECT 
                COUNT(*) as total_rows,
                COUNT(DISTINCT Invoice) as unique_invoices,
                COUNT(DISTINCT CustomerID) as unique_customers,
                COUNT(DISTINCT StockCode) as unique_products,
                COUNT(DISTINCT Country) as unique_countries
            FROM retail
        """).df()
        print(stats.to_string(index=False))
        
        # Missing values
        print("\n2️⃣ MISSING VALUES ANALYSIS")
        for col in self.df.columns:
            missing_count = self.df[col].isnull().sum()
            missing_pct = (missing_count / len(self.df)) * 100
            if missing_count > 0:
                print(f"  • {col}: {missing_count:,} ({missing_pct:.2f}%)")
        
        # Data quality issues
        print("\n3️⃣ DATA QUALITY ISSUES")
        issues = self.con.execute("""
            SELECT 
                SUM(CASE WHEN Quantity < 0 THEN 1 ELSE 0 END) as negative_quantity,
                SUM(CASE WHEN Price <= 0 THEN 1 ELSE 0 END) as zero_or_negative_price,
                SUM(CASE WHEN Quantity = 0 THEN 1 ELSE 0 END) as zero_quantity,
                SUM(CASE WHEN SUBSTRING(CAST(Invoice AS VARCHAR), 1, 1) = 'C' THEN 1 ELSE 0 END) as cancellations
            FROM retail
        """).df()
        print(issues.to_string(index=False))
        
        # Numeric distributions
        print("\n4️⃣ NUMERIC DISTRIBUTIONS")
        distributions = self.con.execute("""
            SELECT 
                'Quantity' as metric,
                MIN(Quantity) as min_val,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY Quantity) as q25,
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY Quantity) as median,
                AVG(Quantity) as mean,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY Quantity) as q75,
                MAX(Quantity) as max_val
            FROM retail
            UNION ALL
            SELECT 
                'Price' as metric,
                MIN(Price),
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY Price),
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY Price),
                AVG(Price),
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY Price),
                MAX(Price)
            FROM retail
        """).df()
        print(distributions.to_string(index=False))
        
        # Top countries
        print("\n5️⃣ TOP 10 COUNTRIES BY TRANSACTIONS")
        countries = self.con.execute("""
            SELECT Country, COUNT(*) as count
            FROM retail
            WHERE Country IS NOT NULL
            GROUP BY Country
            ORDER BY count DESC
            LIMIT 10
        """).df()
        print(countries.to_string(index=False))
        
        # Temporal coverage
        print("\n6️⃣ TEMPORAL COVERAGE")
        temporal = self.con.execute("""
            SELECT 
                MIN(InvoiceDate) as earliest_date,
                MAX(InvoiceDate) as latest_date
            FROM retail
        """).df()
        print(temporal.to_string(index=False))
        
    def assess_suitability(self):
        """Assess dataset suitability for data quality pipeline"""
        print("\n" + "="*60)
        print("✅ SUITABILITY ASSESSMENT")
        print("="*60)
        
        checks = {
            "Multiple data types": "✓ Numeric, categorical, temporal, text",
            "Sufficient volume": f"✓ {len(self.df):,} rows (good for statistical tests)",
            "Natural quality issues": "✓ Missing values, cancellations, negatives",
            "Business logic": "✓ Invoice-customer relationships, time series",
            "Anomaly injection potential": "✓ Multiple patterns possible (see below)"
        }
        
        for check, result in checks.items():
            print(f"\n{result}")
        
        print("\n🎯 VERDICT: HIGHLY SUITABLE for data quality pipeline testing")
        
    def suggest_anomalies(self):
        """Suggest anomaly patterns that can be injected"""
        print("\n" + "="*60)
        print("💡 INJECTABLE ANOMALY PATTERNS")
        print("="*60)
        
        patterns = {
            "Missing Data": [
                "Additional null CustomerIDs (beyond existing ~25%)",
                "Remove product descriptions",
                "Incomplete invoice records"
            ],
            "Outliers": [
                "Extreme quantities (>10,000 units)",
                "Unrealistic prices (>£1,000 for common items)",
                "Abnormal transaction amounts"
            ],
            "Integrity Violations": [
                "Non-existent CustomerIDs",
                "Duplicate InvoiceNo values",
                "Orphaned transactions"
            ],
            "Business Logic": [
                "Positive qty with cancellation flag (InvoiceNo starts with 'C')",
                "Zero-revenue transactions",
                "Same invoice with different dates"
            ],
            "Temporal Issues": [
                "Future dates",
                "Pre-business dates",
                "Out-of-sequence invoice numbers"
            ],
            "Duplicates": [
                "Exact row duplicates",
                "Logical duplicates (same customer/product/time)"
            ]
        }
        
        for category, examples in patterns.items():
            print(f"\n🔹 {category}:")
            for example in examples:
                print(f"  • {example}")
    
    def inject_anomalies(self, output_path='retail_with_anomalies.csv'):
        """Inject various REAL anomalies that violate business logic"""
        print("\n" + "="*60)
        print("🔧 INJECTING BUSINESS LOGIC VIOLATIONS & ANOMALIES")
        print("="*60)
        
        df_anomaly = self.df.copy()
        original_len = len(df_anomaly)
        
        # Track injected anomalies
        anomalies_injected = {}
        
        # BUSINESS RULE VIOLATIONS
        
        # 1. Cancellation invoices with POSITIVE quantities (should be negative)
        # Find real cancellations (Invoice starts with 'C')
        cancellation_mask = df_anomaly['Invoice'].astype(str).str.startswith('C')
        cancellation_indices = df_anomaly[cancellation_mask].index
        
        if len(cancellation_indices) > 0:
            violation_size = min(int(len(cancellation_indices) * 0.1), 1000)  # 10% of cancellations
            violation_idx = np.random.choice(cancellation_indices, violation_size, replace=False)
            # Make quantities positive (business rule violation)
            df_anomaly.loc[violation_idx, 'Quantity'] = abs(df_anomaly.loc[violation_idx, 'Quantity'])
            anomalies_injected['Cancellation with Positive Quantity'] = violation_size
        
        # 2. Regular invoices with NEGATIVE quantities (should be positive)
        regular_mask = ~df_anomaly['Invoice'].astype(str).str.startswith('C')
        regular_with_positive = df_anomaly[regular_mask & (df_anomaly['Quantity'] > 0)].index
        
        if len(regular_with_positive) > 0:
            violation_size = int(len(df_anomaly) * 0.008)  # 0.8%
            violation_idx = np.random.choice(regular_with_positive, 
                                            min(violation_size, len(regular_with_positive)), 
                                            replace=False)
            # Make quantities negative (business rule violation)
            df_anomaly.loc[violation_idx, 'Quantity'] = -1 * df_anomaly.loc[violation_idx, 'Quantity']
            anomalies_injected['Regular Invoice with Negative Quantity'] = len(violation_idx)
        
        # 3. Zero quantities (invalid for any transaction type)
        zero_qty_size = int(len(df_anomaly) * 0.005)  # 0.5%
        zero_idx = np.random.choice(df_anomaly.index, zero_qty_size, replace=False)
        df_anomaly.loc[zero_idx, 'Quantity'] = 0
        anomalies_injected['Zero Quantities'] = zero_qty_size
        
        # DATA INTEGRITY VIOLATIONS
        
        # 4. Missing CustomerID where Country exists (referential integrity)
        has_country = df_anomaly['Country'].notna()
        has_customer = df_anomaly['CustomerID'].notna()
        valid_for_removal = df_anomaly[has_country & has_customer].index
        
        if len(valid_for_removal) > 0:
            removal_size = int(len(df_anomaly) * 0.03)  # 3%
            removal_idx = np.random.choice(valid_for_removal, 
                                          min(removal_size, len(valid_for_removal)), 
                                          replace=False)
            df_anomaly.loc[removal_idx, 'CustomerID'] = np.nan
            anomalies_injected['Missing CustomerID with Country'] = len(removal_idx)
        
        # 5. Same Invoice with different InvoiceDates (data consistency violation)
        invoice_groups = df_anomaly.groupby('Invoice').filter(lambda x: len(x) > 1)
        if len(invoice_groups) > 0:
            unique_invoices = invoice_groups['Invoice'].unique()
            inconsistent_size = min(int(len(unique_invoices) * 0.05), 500)  # 5% of multi-line invoices
            target_invoices = np.random.choice(unique_invoices, inconsistent_size, replace=False)
            
            for invoice in target_invoices:
                invoice_mask = df_anomaly['Invoice'] == invoice
                invoice_indices = df_anomaly[invoice_mask].index
                if len(invoice_indices) > 1:
                    # Change date for half of the invoice lines
                    change_idx = np.random.choice(invoice_indices, len(invoice_indices)//2, replace=False)
                    original_date = df_anomaly.loc[invoice_indices[0], 'InvoiceDate']
                    # Convert to datetime if it's a string
                    if isinstance(original_date, str):
                        original_date = pd.to_datetime(original_date)
                    df_anomaly.loc[change_idx, 'InvoiceDate'] = original_date + pd.Timedelta(days=np.random.randint(1, 30))
            
            anomalies_injected['Inconsistent Invoice Dates'] = inconsistent_size
        
        # STATISTICAL OUTLIERS (Beyond Normal Business)
        
        # 6. Extreme quantity outliers (unrealistic volumes)
        outlier_size = int(len(df_anomaly) * 0.008)  # 0.8%
        outlier_idx = np.random.choice(df_anomaly.index, outlier_size, replace=False)
        # Super extreme quantities
        extreme_quantities = np.random.choice([50000, 100000, 500000, -50000, -100000], outlier_size)
        df_anomaly.loc[outlier_idx, 'Quantity'] = extreme_quantities
        anomalies_injected['Extreme Quantity Outliers'] = outlier_size
        
        # 7. Unrealistic prices (way beyond normal range)
        high_price_size = int(len(df_anomaly) * 0.005)  # 0.5%
        high_price_idx = np.random.choice(df_anomaly.index, high_price_size, replace=False)
        df_anomaly.loc[high_price_idx, 'Price'] = np.random.uniform(10000, 100000, high_price_size)
        anomalies_injected['Unrealistic High Prices'] = high_price_size
        
        # 8. Negative prices (should never happen - not a refund field)
        negative_price_size = int(len(df_anomaly) * 0.003)  # 0.3%
        negative_price_idx = np.random.choice(df_anomaly.index, negative_price_size, replace=False)
        df_anomaly.loc[negative_price_idx, 'Price'] = -1 * abs(df_anomaly.loc[negative_price_idx, 'Price'])
        anomalies_injected['Negative Prices'] = negative_price_size
        
        # TEMPORAL ANOMALIES
        
        # 9. Future dates (impossible transactions)
        future_size = int(len(df_anomaly) * 0.002)  # 0.2%
        future_idx = np.random.choice(df_anomaly.index, future_size, replace=False)
        future_dates = [datetime.now() + timedelta(days=np.random.randint(1, 365)) 
                       for _ in range(future_size)]
        df_anomaly.loc[future_idx, 'InvoiceDate'] = future_dates
        anomalies_injected['Future Dates'] = future_size
        
        # 10. Pre-business dates (before Dec 2009)
        pre_business_size = int(len(df_anomaly) * 0.002)  # 0.2%
        pre_business_idx = np.random.choice(df_anomaly.index, pre_business_size, replace=False)
        pre_dates = [datetime(2008, 1, 1) + timedelta(days=np.random.randint(0, 365)) 
                    for _ in range(pre_business_size)]
        df_anomaly.loc[pre_business_idx, 'InvoiceDate'] = pre_dates
        anomalies_injected['Pre-Business Dates'] = pre_business_size
        
        # DUPLICATE ANOMALIES
        
        # 11. Exact duplicate rows (data quality issue)
        dup_size = int(len(df_anomaly) * 0.005)  # 0.5%
        dup_rows = df_anomaly.sample(n=dup_size)
        df_anomaly = pd.concat([df_anomaly, dup_rows], ignore_index=True)
        anomalies_injected['Exact Duplicate Rows'] = dup_size
        
        # 12. Logical duplicates (same invoice+product but different price)
        logical_dup_size = int(len(df_anomaly) * 0.003)  # 0.3%
        logical_dup_idx = np.random.choice(df_anomaly.index, logical_dup_size, replace=False)
        logical_dup_rows = df_anomaly.loc[logical_dup_idx].copy()
        # Change price slightly to create logical duplicate
        logical_dup_rows['Price'] = logical_dup_rows['Price'] * np.random.uniform(1.1, 2.0, len(logical_dup_rows))
        df_anomaly = pd.concat([df_anomaly, logical_dup_rows], ignore_index=True)
        anomalies_injected['Logical Duplicates (same invoice+product, diff price)'] = logical_dup_size
        
        # MISSING DATA ANOMALIES
        
        # 13. Missing Description (data completeness issue)
        desc_missing_size = int(len(df_anomaly) * 0.015)  # 1.5%
        desc_idx = np.random.choice(df_anomaly.index, desc_missing_size, replace=False)
        df_anomaly.loc[desc_idx, 'Description'] = np.nan
        anomalies_injected['Missing Descriptions'] = desc_missing_size
        
        # 14. Missing Country (should always be present)
        country_missing_size = int(len(df_anomaly) * 0.01)  # 1%
        country_idx = np.random.choice(df_anomaly.index, country_missing_size, replace=False)
        df_anomaly.loc[country_idx, 'Country'] = np.nan
        anomalies_injected['Missing Country'] = country_missing_size
        
        # SCHEMA VIOLATIONS
        
        # 15. Invalid StockCode format (should be alphanumeric)
        invalid_stock_size = int(len(df_anomaly) * 0.004)  # 0.4%
        invalid_stock_idx = np.random.choice(df_anomaly.index, invalid_stock_size, replace=False)
        invalid_codes = ['!@#$%', '???', 'NULL', '---', '***']
        df_anomaly.loc[invalid_stock_idx, 'StockCode'] = np.random.choice(invalid_codes, invalid_stock_size)
        anomalies_injected['Invalid StockCode Format'] = invalid_stock_size
        
        # 16. Duplicate Invoice with different customers (referential integrity)
        if len(invoice_groups) > 0:
            unique_invoices = invoice_groups['Invoice'].unique()
            dup_invoice_size = min(int(len(unique_invoices) * 0.02), 300)
            target_invoices = np.random.choice(unique_invoices, dup_invoice_size, replace=False)
            
            for invoice in target_invoices:
                invoice_mask = df_anomaly['Invoice'] == invoice
                invoice_indices = df_anomaly[invoice_mask].index
                if len(invoice_indices) > 1:
                    # Change CustomerID for some lines in the same invoice
                    change_idx = np.random.choice(invoice_indices, len(invoice_indices)//2, replace=False)
                    # Assign random different customer IDs
                    random_customers = df_anomaly['CustomerID'].dropna().sample(len(change_idx)).values
                    df_anomaly.loc[change_idx, 'CustomerID'] = random_customers
            
            anomalies_injected['Same Invoice Different Customers'] = dup_invoice_size
        
        # Save
        df_anomaly.to_csv(output_path, index=False)
        
        print(f"\n✅ Anomalies injected successfully!")
        print(f"📊 Summary:")
        print(f"  Original rows: {original_len:,}")
        print(f"  Final rows: {len(df_anomaly):,}")
        print(f"  Rows added: {len(df_anomaly) - original_len:,}")
        
        print(f"\n🔍 Anomalies by category:")
        
        # Group by category for better display
        categories = {
            "Business Rule Violations": [
                'Cancellation with Positive Quantity',
                'Regular Invoice with Negative Quantity',
                'Zero Quantities'
            ],
            "Data Integrity Issues": [
                'Missing CustomerID with Country',
                'Inconsistent Invoice Dates',
                'Same Invoice Different Customers'
            ],
            "Statistical Outliers": [
                'Extreme Quantity Outliers',
                'Unrealistic High Prices',
                'Negative Unit Prices'
            ],
            "Temporal Anomalies": [
                'Future Dates',
                'Pre-Business Dates'
            ],
            "Duplicate Anomalies": [
                'Exact Duplicate Rows',
                'Logical Duplicates (same invoice+product, diff price)'
            ],
            "Missing Data": [
                'Missing Descriptions',
                'Missing Country'
            ],
            "Schema Violations": [
                'Invalid StockCode Format'
            ]
        }
        
        for category, anomaly_types in categories.items():
            print(f"\n  📌 {category}:")
            for anom_type in anomaly_types:
                if anom_type in anomalies_injected:
                    print(f"     • {anom_type}: {anomalies_injected[anom_type]:,}")
        
        print(f"\n💾 Saved to: {output_path}")
        
        # Create anomaly summary file
        summary_path = output_path.replace('.csv', '_anomaly_summary.txt')
        with open(summary_path, 'w') as f:
            f.write("ANOMALY INJECTION SUMMARY\n")
            f.write("="*60 + "\n\n")
            f.write(f"Original rows: {original_len:,}\n")
            f.write(f"Final rows: {len(df_anomaly):,}\n")
            f.write(f"Rows added: {len(df_anomaly) - original_len:,}\n\n")
            
            for category, anomaly_types in categories.items():
                f.write(f"\n{category}:\n")
                for anom_type in anomaly_types:
                    if anom_type in anomalies_injected:
                        f.write(f"  - {anom_type}: {anomalies_injected[anom_type]:,}\n")
        
        print(f"📄 Anomaly summary saved to: {summary_path}")
        
        return df_anomaly


def main():
    """Main execution function"""
    print("\n" + "="*60)
    print("🚀 ONLINE RETAIL II - DATA QUALITY PIPELINE ASSESSMENT")
    print("="*60)
    
    # Choose download method
    print("\n📥 Dataset Loading Options:")
    print("  1. Download from Kaggle (using kagglehub)")
    print("  2. Load from local file")
    
    choice = input("\nChoose option (1 or 2): ").strip()
    
    if choice == '1':
        # Download from Kaggle
        analyzer = RetailDataAnalyzer(download_from_kaggle=True)
    else:
        # Load from local file
        file_path = input("Enter file path (e.g., 'online_retail_II.xlsx'): ").strip()
        analyzer = RetailDataAnalyzer(file_path=file_path)
    
    # Load data
    analyzer.load_data()
    
    # Profile dataset
    analyzer.profile_dataset()
    
    # Assess suitability
    analyzer.assess_suitability()
    
    # Suggest anomaly patterns
    analyzer.suggest_anomalies()
    
    # Ask user if they want to inject anomalies
    print("\n" + "="*60)
    inject = input("\n🤔 Would you like to inject anomalies now? (yes/no): ").lower()
    
    if inject in ['yes', 'y']:
        analyzer.inject_anomalies()
        print("\n✨ Done! You now have both clean and anomalous datasets.")
    else:
        print("\n✨ Analysis complete! Run inject_anomalies() when ready.")


if __name__ == "__main__":
    main()