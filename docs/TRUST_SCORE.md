# Trust Score System

## Overview

The Trust Score measures a user's profile completeness and verification status across four key dimensions: Identity, Employment, Education, and Documents. The overall score (0-100) helps users understand their profile strength and what's needed for improvement.

## Calculation Formula

### Component Scores (0-100 each)

#### Identity Score (30% weight)
Measures personal profile completeness:
- Email verified: **50 points**
- Full name provided: **25 points**
- Profile slug set: **25 points**
- **Maximum: 100 points**

**Example:**
- Unverified email, no name, no slug = 0/100
- Verified email, has name, has slug = 100/100
- Verified email only = 50/100

#### Employment Score (25% weight)
Measures employment verification status:
- **If no employments:** 0 points
- **If employments exist:** (verified count / total count) × 100

Verified employments are those with status: `approved` or `verified`

**Example:**
- 0 employments = 0/100
- 1 total, 0 verified = 0/100
- 2 total, 1 verified = 50/100
- 3 total, 3 verified = 100/100

#### Education Score (20% weight)
Measures education credential verification:
- **If no education:** 0 points
- **If education exists:** (verified count / total count) × 100

Verified education has status: `approved` or `verified`

**Example:**
- 0 education records = 0/100
- 2 total, 1 verified = 50/100
- 2 total, 2 verified = 100/100

#### Documents Score (25% weight)
Measures identity document verification:
- **If no documents:** 0 points
- **If documents exist:** (verified count / total count) × 100

Verified documents have status: `approved` or `verified`

**Example:**
- 0 documents = 0/100
- 1 total, 0 verified = 0/100
- 2 total, 1 verified = 50/100

### Overall Score Calculation

```
Overall Score = (
    Identity × 0.30 +
    Employment × 0.25 +
    Education × 0.20 +
    Documents × 0.25
)
```

**Ranges:**
- **0-25:** Minimal profile setup
- **26-50:** Basic profile in progress
- **51-75:** Good profile completeness
- **76-100:** Highly verified profile

## API Endpoint

### Get Trust Score

```http
GET /api/v1/trust-score
Authorization: Bearer {token}
```

#### Response

```json
{
  "overall": 72,
  "breakdown": {
    "identity": 95,
    "employment": 70,
    "education": 60,
    "documents": 55
  },
  "week_change": 7
}
```

**Fields:**
- `overall`: Overall trust score (0-100)
- `breakdown.identity`: Identity verification score
- `breakdown.employment`: Employment verification score
- `breakdown.education`: Education credential score
- `breakdown.documents`: Document verification score
- `week_change`: Change in overall score over past week

## Implementation Details

### Service Class
**File:** `app/services/trust_score_service.py`

The `TrustScoreService` class handles all score calculations:
- `calculate_trust_score(user_id)` - Main entry point
- `_calculate_identity_score(user)` - Identity component
- `_calculate_employment_score(user_id)` - Employment component
- `_calculate_education_score(user_id)` - Education component
- `_calculate_documents_score(user_id)` - Document component
- `_calculate_weighted_overall(breakdown)` - Weighted average

### Routes
**File:** `app/api/v1/routes/trust_score.py`

Defines the HTTP endpoints for accessing trust scores.

### Schemas
**File:** `app/schemas/trust_score.py`

Defines response models:
- `TrustScoreComponentBreakdown` - Individual component scores
- `TrustScoreResponse` - Complete response with overall score

## Verification Statuses

Components are considered "verified" when their status is:
- `approved`
- `verified`

Statuses in progress (e.g., `draft`, `submitted`, `under_review`, `pending`) do not count as verified.

## Future Enhancements

1. **Week Change Calculation** - Currently returns 0. Implement by comparing current score to historical snapshot from 7 days ago.
2. **Score Trends** - Track score changes over time for insights.
3. **Verification Recommendations** - Suggest specific actions to improve score.
4. **Weighted Dynamic Weights** - Allow different weights based on user role or use case.

## Testing

Test the endpoint with a verified user:

```bash
curl -H "Authorization: Bearer {token}" \
  http://localhost:8000/api/v1/trust-score
```

Expected response for fully verified user:
```json
{
  "overall": 100,
  "breakdown": {
    "identity": 100,
    "employment": 100,
    "education": 100,
    "documents": 100
  },
  "week_change": 0
}
```
