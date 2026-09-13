// Clean, single-column ATS-friendly Typst Layout
#let cv(
    name: "",
    contact_info: (),
    summary: "",
    body
) = {
    set page(
        paper: "a4",
        margin: (x: 1.8cm, y: 1.8cm)
    )

    set text(
        font: ("Liberation Sans", "Arial", "DejaVu Sans"),
        size: 10pt,
        fill: rgb("#111111"),
        lang: "en"
    )

    set par(justify: false, leading: 0.65em)

    // Header Block
    align(center)[
        #block(width: 100%)[
            #text(weight: "bold", size: 20pt)[#name] \
            #v(3pt)
            #text(size: 9.5pt, fill: rgb("#333333"))[
                #contact_info.join("  |  ")
            ]
        ]
    ]

    v(6pt)

    // Executive Summary
    if summary != "" [
        #text(weight: "bold", size: 11pt, fill: rgb("#003366"))[PROFESSIONAL SUMMARY]
        #v(-4pt)
        #line(length: 100%, stroke: 0.5pt + rgb("#cccccc"))
        #v(2pt)
        #summary
        #v(8pt)
    ]

    body
}

#let cv_section(title) = {
    v(10pt)
    text(weight: "bold", size: 11pt, fill: rgb("#003366"))[#upper(title)]
    v(-4pt)
    line(length: 100%, stroke: 0.5pt + rgb("#cccccc"))
    v(4pt)
}

#let job_header(title, company, dates, location) = {
    block(width: 100%)[
        #grid(
            columns: (1fr, auto),
            [*#title* #sym.dash.em #emph(company)],
            [*#dates*],
        )
        #if location != "" [
            #text(size: 9pt, style: "italic", fill: rgb("#555555"))[#location]
        ]
    ]
    v(2pt)
}
