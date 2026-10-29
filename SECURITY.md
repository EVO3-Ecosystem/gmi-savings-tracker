# Security

The pipeline reads only public data from opendata.maryland.gov. Never commit an app token: put `MD_SODA_APP_TOKEN` in `.env` (git-ignored) locally, or in the repository's Actions secrets.
