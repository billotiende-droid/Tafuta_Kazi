// Clean, single-column ATS-friendly Typst Layout
#let cv(
    name: "",
    contact_info: (),
    summary: "",
    body
) = {
    #set page(
        paper:"a4",
        margin: (x: 1.8cm, y: 1.8cm)
    )

    #set text(
        font: ("Liberation Sans", "Arial", "DejaVu Sans"),
        size: 10pt,
        fill: rgb("#111111"),
        lang: "en:
    )

    #set par(justify: false, leading: 0.65em)

    // Header Block
    #align(center)[
    #block(width: 100%)[
      #text(weight: "bold", size: 20pt)[#name] \
      #v(3pt)
      #text(size: 9.5pt, fill: rgb("#333333"))[
        #contact_info.join("  |  ")
      ]
    ]
  ]

  #v(6pt)

}