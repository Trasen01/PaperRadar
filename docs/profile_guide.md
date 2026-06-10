# Research Profile Guide

PaperRadar uses research Profiles to decide search queries, keyword groups, exclusion terms, and recommended journals.

## Create a Profile with an External AI

1. Open the research direction page.
2. Enter a direction, for example `ultrafast photonics`.
3. Click the button that generates and copies the AI prompt.
4. Paste the prompt into an external AI tool.
5. Use the AI tool's copy button or copy shortcut, if available, to copy the full YAML output.
6. Paste it back into PaperRadar.
7. Use smart parsing and save it as the current direction.

## Required YAML Fields

```yaml
profile_version: 1
profile_id: ultrafast_photonics
display_name: 超快光子学
description: Ultrafast photonics research profile.
search_queries:
  - ultrafast photonics
keyword_groups:
  core:
    priority: high
    terms:
      - ultrafast photonics
exclude_terms: []
recommended_journals:
  - Nature
  - Science
```

PaperRadar can repair some incomplete YAML and can convert a pasted keyword list into a temporary Profile, but a complete YAML Profile is preferred.
