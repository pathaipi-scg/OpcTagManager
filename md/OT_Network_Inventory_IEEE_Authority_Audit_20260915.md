# IEEE Registration Authority vendor audit

## Conclusion

The value is a correct extraction from the local IEEE CSV, not a field-mapping
or normalization bug. No runtime/parser changes were made.

Read-only production SQL inspection found NetworkId **1**, IP **172.28.231.23**,
MAC **00:50:C2:CE:AE:47**, stored Vendor **IEEE Registration Authority**,
ScanTime **2026-09-15 15:36:47.248 UTC**.

`normalize_mac()` returns `00:50:C2:CE:AE:47`; the lookup takes its first eight
characters, `00:50:C2`, representing 24 bits. Removing the separators matches
CSV Assignment `0050C2`. `load_oui_file()` explicitly reads `Organization Name`,
not `Registry` or `Organization Address`. Exactly one CSV row matches.

## Exact CSV fields

Source: `D:\AI\OpcTagManager\data\oui.csv`.
The address's trailing space is preserved inside the JSON string below.

```json
{
  "Registry": "MA-L",
  "Assignment": "0050C2",
  "Organization Name": "IEEE Registration Authority",
  "Organization Address": "445 Hoes Lane Piscataway NJ US 08554 "
}
```

This is valid as the registered 24-bit prefix owner, not confirmation that IEEE
manufactured the device. IEEE explains that Individual Address Blocks (IABs)
use its own OUI plus 12 additional assignment bits, and that `00:50:C2` was used
for IAB assignments. A 24-bit MA-L lookup cannot identify the smaller-block
assignee. See [IEEE Registration Authority FAQs](https://standards.ieee.org/faqs/regauth/).
No replacement manufacturer was guessed and no new runtime Internet lookup
or additional registry loading was introduced.

## Cross-checks through the same local parser

All rows below have NetworkId 1. Stored vendor, matching CSV Organization Name,
and `load_oui_file()` lookup agree exactly.

| IP | Stored MAC | Normalized prefix | CSV Assignment | Organization Name |
|---|---|---|---|---|
| 172.28.231.23 | 00:50:C2:CE:AE:47 | 00:50:C2 | 0050C2 | IEEE Registration Authority |
| 172.28.231.120 | 00:30:DE:5A:EC:19 | 00:30:DE | 0030DE | WAGO Kontakttechnik GmbH |
| 172.28.231.102 | 30:B8:51:35:C5:7C | 30:B8:51 | 30B851 | Siemens AG |
| 172.28.231.10 | 00:E0:4C:50:CB:38 | 00:E0:4C | 00E04C | REALTEK SEMICONDUCTOR CORP. |

Other latest rows with this authority name were `172.28.231.18` (prefix
`04:EE:E8`) and `.61`, `.62`, `.63` (prefix `44:6F:D8`). Their matching MA-L CSV
rows also explicitly name IEEE Registration Authority and have the same IEEE
organization address. These are not accidental reads of the Registry field.

Regression fixtures copy the four verified CSV rows into temporary files and
exercise normalization, lookup, Organization Name extraction, current-row
resolution, and reordered CSV headers. Tests never probe or persist these MACs.
The existing JSON parser and its regression coverage remain unchanged.

No scan, production restart, SQL mutation, or configuration change was performed.
