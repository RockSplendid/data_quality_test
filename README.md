# Anomaly Injection Code - Key Improvements

## 🎯 Overview

This document outlines the critical improvements made to the anomaly injection approach for the Online Retail II dataset, transforming it from a naive pattern-matching system to a business-logic-aware data quality testing framework.

---

## Before: Naive Approach ❌

### What Was Wrong

**1. Misidentified Legitimate Business Data as Anomalies**
- Treated negative quantities as anomalies
  - Reality: Negative quantities are valid returns/cancellations (InvoiceNo starts with 'C')
- Flagged negative prices as errors
  - Reality: These could be legitimate adjustments or refunds
- Considered missing CustomerIDs as data quality issues
  - Reality: These represent documented guest checkouts

**2. Didn't Respect Business Logic**
- No understanding of cancellation rules
- No validation of invoice-customer relationships
- No temporal business constraints
- Generic violations that don't reflect real-world issues

**3. Limited Testing Scope**
- Only 8 generic anomaly types
- No category organization
- Missing critical business rule violations
- No differentiation between severity levels

---

## After: Business-Logic Aware Approach ✅

### What Changed

**1. Respects Actual Business Rules**
- Understands that cancellations (InvoiceNo starts with 'C') should have negative quantities
- Recognizes that regular invoices should have positive quantities
- Validates invoice-level consistency (same invoice = same date, same customer)
- Enforces referential integrity rules

**2. Injects TRUE Violations**
- **Business Rule Violations**: Operations that break documented business logic
- **Data Integrity Issues**: Violations of relational constraints
- **Statistical Outliers**: Values beyond reasonable business ranges
- **Temporal Anomalies**: Impossible or chronologically invalid dates
- **Duplicate Anomalies**: Various forms of data duplication
- **Missing Data**: Strategic absence of required fields
- **Schema Violations**: Format and type constraints

**3. Comprehensive Testing Framework**
- **16 distinct anomaly types** (up from 8)
- **7 organized categories** for systematic testing
- **Detailed tracking** with summary reports
- **Realistic distributions** based on actual business scenarios

---

## 📋 New Anomaly Types (16 Total)

### 1. Business Rule Violations (4 types)

| Anomaly | Description | Why It Matters |
|---------|-------------|----------------|
| **Cancellation with Positive Quantity** | InvoiceNo starts with 'C' but Quantity > 0 | Violates core business logic: cancellations must reduce inventory |
| **Regular Invoice with Negative Quantity** | InvoiceNo doesn't start with 'C' but Quantity < 0 | Invalid: only cancellations can have negative quantities |
| **Zero Quantities** | Any transaction with Quantity = 0 | Meaningless transaction: no items exchanged |
| **Same Invoice Different Customers** | One InvoiceNo assigned to multiple CustomerIDs | Referential integrity violation: invoices belong to one customer |

### 2. Data Integrity Issues (3 types)

| Anomaly | Description | Why It Matters |
|---------|-------------|----------------|
| **Missing CustomerID with Country** | Country exists but CustomerID is null | Illogical: if you know where they're from, you should know who they are |
| **Inconsistent Invoice Dates** | Same InvoiceNo has different InvoiceDates | Impossible: an invoice is created at one point in time |
| **Invoice-Customer Inconsistency** | Related records don't match expected relationships | Breaks referential integrity assumptions |

### 3. Statistical Outliers (3 types)

| Anomaly | Description | Why It Matters |
|---------|-------------|----------------|
| **Extreme Quantity Outliers** | Quantities of 50K-500K units | Beyond reasonable business scale (testing outlier detection) |
| **Unrealistic High Prices** | Unit prices of £10K-100K | Far exceeds typical product pricing (statistical anomaly) |
| **Negative Unit Prices** | UnitPrice < 0 | Invalid: prices can't be negative (different from refunds) |

### 4. Temporal Anomalies (2 types)

| Anomaly | Description | Why It Matters |
|---------|-------------|----------------|
| **Future Dates** | Transactions dated after current date | Impossible: can't record what hasn't happened |
| **Pre-Business Dates** | Transactions before Dec 2009 | Invalid: business didn't exist yet |

### 5. Duplicate Anomalies (2 types)

| Anomaly | Description | Why It Matters |
|---------|-------------|----------------|
| **Exact Duplicate Rows** | Identical records appearing multiple times | Data quality issue: accidental duplication |
| **Logical Duplicates** | Same invoice+product but different price | Business logic violation: price should be consistent |

### 6. Missing Data (2 types)

| Anomaly | Description | Why It Matters |
|---------|-------------|----------------|
| **Missing Descriptions** | Product description is null | Completeness issue: reduces data utility |
| **Missing Country** | Country field is null | Critical field: should always be present |

### 7. Schema Violations (1 type)

| Anomaly | Description | Why It Matters |
|---------|-------------|----------------|
| **Invalid StockCode Format** | Special characters, NULL strings, etc. | Format validation: codes should follow patterns |

---

## 🎁 Additional Features

### 1. Categorized Output
Anomalies are now grouped by category for easier analysis:
```
Business Rule Violations:
  • Cancellation with Positive Quantity: 1,234
  • Regular Invoice with Negative Quantity: 854

Data Integrity Issues:
  • Missing CustomerID with Country: 3,210
  • Inconsistent Invoice Dates: 500
```

### 2. Anomaly Summary File
Automatically generates a text file (`*_anomaly_summary.txt`) containing:
- Total rows (original vs final)
- Complete breakdown by category
- Count for each anomaly type
- Easy reference for pipeline testing

### 3. Smart Injection Logic
- Respects existing data patterns
- Uses realistic distributions
- Avoids overwriting legitimate data unnecessarily
- Maintains statistical properties of the original dataset

### 4. Configurable Injection Rates
Each anomaly type has a tuned injection rate:
- Critical violations: 0.5-1% (realistic rarity)
- Common issues: 1-3% (more frequent)
- Rare problems: 0.2-0.5% (edge cases)

---

## 💡 Why This Matters for Your Pipeline

### Before (Naive Approach)
```python
# False Positives
if quantity < 0:
    flag_as_anomaly()  # ❌ Wrong! Could be a valid return

if customer_id is None:
    flag_as_anomaly()  # ❌ Wrong! Could be guest checkout
```

### After (Business-Logic Aware)
```python
# True Validation
if invoice_no.startswith('C') and quantity > 0:
    flag_as_anomaly()  # ✅ Correct! Cancellation should be negative

if not invoice_no.startswith('C') and quantity < 0:
    flag_as_anomaly()  # ✅ Correct! Regular sale should be positive
```

### Benefits
1. **No False Positives**: Your pipeline learns to distinguish legitimate patterns from errors
2. **Realistic Testing**: Anomalies mirror actual production issues
3. **Comprehensive Coverage**: Tests multiple failure modes
4. **Measurable Quality**: Clear metrics for detection accuracy
5. **Production-Ready**: Rules transfer directly to real monitoring

---

## 📊 Injection Statistics

| Category | Number of Types | Typical Injection Rate | Priority |
|----------|----------------|----------------------|----------|
| Business Rule Violations | 4 | 0.8-3% | 🔴 Critical |
| Data Integrity Issues | 3 | 1-5% | 🔴 Critical |
| Statistical Outliers | 3 | 0.3-0.8% | 🟡 High |
| Temporal Anomalies | 2 | 0.2-0.4% | 🟡 High |
| Duplicate Anomalies | 2 | 0.5-0.8% | 🟢 Medium |
| Missing Data | 2 | 1-2.5% | 🟢 Medium |
| Schema Violations | 1 | 0.4% | 🟢 Medium |

**Total**: ~10-15% of records affected (with some overlap possible)

---

## 🚀 Next Steps for Your Pipeline

With these realistic anomalies, you can now build detection rules for:

1. **Business Logic Validators**
   - Cancellation quantity checks
   - Invoice consistency validators
   - Cross-field validation rules

2. **Statistical Monitors**
   - Outlier detection algorithms
   - Distribution shift detection
   - Anomaly scoring systems

3. **Data Quality Metrics**
   - Completeness scores
   - Consistency rates
   - Accuracy measurements

4. **Alerting Rules**
   - Critical violations → immediate alerts
   - Medium issues → daily reports
   - Low priority → weekly summaries

---

## 📝 Summary

| Aspect | Before | After |
|--------|--------|-------|
| **Anomaly Types** | 8 generic | 16 business-specific |
| **Categories** | Unorganized | 7 structured categories |
| **Business Logic** | ❌ Ignored | ✅ Enforced |
| **False Positives** | High | Minimal |
| **Real-World Applicability** | Low | High |
| **Testing Coverage** | Basic | Comprehensive |
| **Documentation** | Minimal | Detailed summary files |

---

## 🎯 Conclusion

The improved anomaly injection approach transforms your data quality pipeline from a simple pattern matcher into a sophisticated business-logic-aware validation system. By respecting the actual semantics of the data and injecting true violations, you can build detection systems that work effectively in production environments.

**Key Takeaway**: Always understand your data's business context before defining what constitutes an "anomaly." What looks like an error might be a legitimate business pattern, and vice versa.
