# Lucide icons

The tool's icons come from [Lucide](https://lucide.dev) (licence ISC, see `LICENSE`).

| File | Content |
|---|---|
| `lucide.json` | The whole Lucide set in Iconify format (`@iconify-json/lucide` 1.2.151, from the npm registry), unchanged |
| `lucide-info.json` | Name, author, licence and size of the set |
| `LICENSE` | Lucide licence (ISC), with the MIT notice of the Feather icons it includes (from the `lucide` package 1.68.0) |

Use an icon in a template:

```django
{% load collecte %}{% icone "chevron-down" %}        {# any Lucide name #}
{% icone "telecharger" %}                          {# a name of the tool, mapped in ICONES #}
{% icone "search" "" %}                            {# without the icone-svg class #}
```

`collecte/templatetags/collecte.py` reads the file once, maps the tool's names to Lucide names (`ICONES`) and writes
the SVG into the page: no external service is called. Browse the set at https://lucide.dev/icons or
https://icon-sets.iconify.design/lucide/. To update: download `@iconify-json/lucide` from the npm registry and replace
`lucide.json` and `lucide-info.json`, then run `python3 manage.py test collecte.test_icones`.
