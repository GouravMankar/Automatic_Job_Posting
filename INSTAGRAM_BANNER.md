# Instagram Banner Template

The channel renderer now produces a 1080x1350 PNG designed for Instagram portrait posts.

## Layout

- Hero area: company branding, `HIRING ALERT`, wrapped job title, and a visual area.
- Details card: company, location, experience, batch/eligibility, salary, employment type, posted date, and last date.
- Lower panels: required skills and job highlights.
- CTA: `FOLLOW + COMMENT 'LINK' FOR APPLY URL`.
- Footer: `Good Opportunities. Better Careers.`

## Optional company assets

Place permitted company artwork in:

```text
jobhunt/channel_assets/companies/
```

Supported names:

```text
company-slug.png
company-slug.jpg
company-slug.webp
company-slug_hero.png
company-slug_hero.jpg
company-slug_hero.webp
```

The base company image is treated as a logo/brand image. The `_hero` version is used as the large visual on the right side of the header.

If no company images are provided, the renderer creates a neutral blue tech/building illustration instead of inventing company-specific branding.

## Data accuracy

Salary, batch, eligibility, skills, employment type, and deadlines are rendered only when they can be extracted from the job record/description. Missing values appear as `Not specified` rather than being guessed.
