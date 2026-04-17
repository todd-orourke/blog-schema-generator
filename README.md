# Blog Posting Schema Markup Generator

A Python-native tool to extract metadata from URLs and generate structured JSON-LD schema (WebSite, BlogPosting, Organization, Breadcrumbs, and FAQ).

## Features
* **Deterministic JSON:** Uses Python dicts rather than LLM-generated strings to ensure valid JSON-LD.
* **Auto-Extraction:** Uses BeautifulSoup and Trafilatura to pull titles, dates, and body text.
* **FAQ Generation:** Optional integration with Gemini 2.5 Flash to generate FAQ answers based on article context.

## Setup
1. Clone this repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
