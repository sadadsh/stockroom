

def test_the_extraction_cascade_records_no_intra_document_conflicts():
    """A real page carries an og:title AND JSON-LD AND a spec table. Whatever they disagree
    about must not land in the part's alternate-value lists: those exist to show a
    DigiKey-vs-Mouser difference, and page-parsing noise would drown it."""
    from stockroom.scrape.extract import extract_product

    html = """
    <html><head>
      <meta property="og:title" content="TPS62130RGTR - Texas Instruments | Mouser">
      <meta property="og:description" content="Buy TPS62130RGTR on Mouser Electronics">
      <script type="application/ld+json">
        {"@type":"Product","name":"TPS62130RGTR","description":"3A Step-Down Converter",
         "brand":{"name":"Texas Instruments"}}
      </script>
    </head><body><h1>Some Other Heading Entirely</h1></body></html>
    """
    r = extract_product(html, "https://example.com/p", [])
    assert r.field_conflicts == {}, r.field_conflicts
    assert r.spec_conflicts == {}, r.spec_conflicts
