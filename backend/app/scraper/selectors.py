"""
Centralized selectors for Monster.com. Update when markup changes.

Use multiple fallback selectors per field (first match wins in scraper logic).
"""

LISTING_JOB_CARD_SELECTORS = [
    "div[data-testid='JobCard']",
    "div.job-card",
    "article.job-search-result",
    "[class*='JobCard']",
    "[class*='job-card']",
    "div[data-jobid]",
    "li[data-test='jobListing']",
    "li[data-testid='job-results-list-item-wrapper']",
    "section[data-job-id]",
    "div[data-job-id]",
    "article[class*='job']",
]

LISTING_TITLE_SELECTORS = [
    "h3 a",
    "h2 a",
    "[data-testid='job-card-title'] a",
    "a[data-testid='jobTitle']",
    "a.JobCard_jobTitle",
]

LISTING_COMPANY_SELECTORS = [
    "[data-testid='company']",
    "span.company-name",
    "div[class*='company']",
]

LISTING_LOCATION_SELECTORS = [
    "[data-testid='jobDetailLocation']",
    "span[class*='location']",
    "[class*='job-card-location']",
]

LISTING_SALARY_SELECTORS = [
    "[data-testid='jobDetailSalary']",
    "[class*='salary']",
]

LISTING_LINK_SELECTORS = [
    "h3 a",
    "h2 a",
    "a[data-testid='jobTitle']",
]

LISTING_POSTED_SELECTORS = [
    "[data-testid='jobDetailDate']",
    "time",
    "[class*='posted']",
    "[class*='date']",
]

DETAIL_CONTAINER_SELECTORS = [
    "[data-testid='jobDescription']",
    "div[class*='job-description']",
    "div[class*='JobDescription']",
    "#jobDescription",
    "main",
]

DETAIL_TITLE_SELECTORS = ["h1", "[data-testid='jobTitle']"]
