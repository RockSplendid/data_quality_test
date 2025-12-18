import duckdb
import pandas as pd

# Load data
df = pd.read_csv('/home/codespace/.cache/kagglehub/datasets/mashlyn/online-retail-ii-uci/versions/3/online_retail_II.csv')

# Clean column names - replace spaces with underscores
df.columns = df.columns.str.replace(' ', '')

con = duckdb.connect(':memory:')
con.register('retail', df)

# Show a quick sample before further analysis
# print("=== SAMPLE (FIRST 5 ROWS) ===")
# pd.set_option('display.max_columns', None)
# pd.set_option('display.width', None)
# print(df.head())


# 1. Basic Statistics
print("=== BASIC STATISTICS ===")
stats = con.execute("""
    SELECT 
        COUNT(*) as total_rows,
        COUNT(DISTINCT Invoice) as unique_invoices,
        COUNT(DISTINCT CustomerID) as unique_customers,
        COUNT(DISTINCT StockCode) as unique_products,
        COUNT(DISTINCT Country) as unique_countries
    FROM retail
""").df()
print(stats)

# 2. Missing Values Analysis
print("\n=== MISSING VALUES ===")
missing = con.execute("""
    SELECT 
        COUNT(*) as total_rows,
        SUM(CASE WHEN CustomerID IS NULL THEN 1 ELSE 0 END) as missing_customer,
        SUM(CASE WHEN Description IS NULL THEN 1 ELSE 0 END) as missing_description,
        SUM(CASE WHEN Invoice IS NULL THEN 1 ELSE 0 END) as missing_invoice
    FROM retail
""").df()
print(missing)

# 3. Data Quality Issues
print("\n=== DATA QUALITY ISSUES ===")
issues = con.execute("""
    SELECT 
        SUM(CASE WHEN Quantity < 0 THEN 1 ELSE 0 END) as negative_quantity,
        SUM(CASE WHEN Price <= 0 THEN 1 ELSE 0 END) as zero_or_negative_price,
        SUM(CASE WHEN Quantity = 0 THEN 1 ELSE 0 END) as zero_quantity,
        SUM(CASE WHEN LEFT(Invoice, 1) = 'C' THEN 1 ELSE 0 END) as cancellations
    FROM retail
""").df()
print(issues)

# 4. Numeric Distributions
print("\n=== NUMERIC DISTRIBUTIONS ===")
distributions = con.execute("""
    SELECT 
        MIN(Quantity) as min_qty,
        AVG(Quantity) as avg_qty,
        MAX(Quantity) as max_qty,
        MIN(Price) as min_price,
        AVG(Price) as avg_price,
        MAX(Price) as max_price
    FROM retail
""").df()
print(distributions)

# 5. Top Countries
print("\n=== TOP 10 COUNTRIES ===")
countries = con.execute("""
    SELECT Country, COUNT(*) as transaction_count
    FROM retail
    WHERE Country IS NOT NULL
    GROUP BY Country
    ORDER BY transaction_count DESC
    LIMIT 10
""").df()
print(countries)

# 6. Temporal Coverage
print("\n=== TEMPORAL COVERAGE ===")
temporal = con.execute("""
    SELECT 
        MIN(InvoiceDate) as earliest_date,
        MAX(InvoiceDate) as latest_date,
        COUNT(DISTINCT DATE(InvoiceDate)) as unique_days
    FROM retail
""").df()
print(temporal)
