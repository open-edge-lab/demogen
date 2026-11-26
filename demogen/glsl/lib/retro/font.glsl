// retro/font.glsl — font bitmap 8x8 ORIGINALE (disegnato per demogen, 96 glifi
// ASCII 32..127; i glifi non disegnati sono vuoti). Il testo arriva da uText[64]
// (4 caratteri ASCII per int, little-endian) + uTextLen: è un dato, non codice.

/// @fn fontGlyph
/// ritorna i 64 bit del glifo 8x8: riga 0 = byte alto di .x, bit 7 = colonna 0.
uvec2 fontGlyph(int code) {
    // glifi disegnati: spazio ! , - . : ? 0-9 A-Z (il resto è vuoto)
    const uvec2 F[96] = uvec2[96](
        uvec2(0x00000000u, 0x00000000u), // 32 spazio
        uvec2(0x18181818u, 0x18001800u), // 33 !
        uvec2(0x00000000u, 0x00000000u), // 34 "
        uvec2(0x00000000u, 0x00000000u), // 35 #
        uvec2(0x00000000u, 0x00000000u), // 36 $
        uvec2(0x00000000u, 0x00000000u), // 37 %
        uvec2(0x00000000u, 0x00000000u), // 38 &
        uvec2(0x00000000u, 0x00000000u), // 39 '
        uvec2(0x00000000u, 0x00000000u), // 40 (
        uvec2(0x00000000u, 0x00000000u), // 41 )
        uvec2(0x00000000u, 0x00000000u), // 42 *
        uvec2(0x00000000u, 0x00000000u), // 43 +
        uvec2(0x00000000u, 0x00181830u), // 44 ,
        uvec2(0x0000FC00u, 0x00000000u), // 45 -
        uvec2(0x00000000u, 0x00001800u), // 46 .
        uvec2(0x00000000u, 0x00000000u), // 47 /
        uvec2(0x3C464A52u, 0x62423C00u), // 48 0
        uvec2(0x18381818u, 0x18187E00u), // 49 1
        uvec2(0x3C42023Cu, 0x40407E00u), // 50 2
        uvec2(0x3C42021Cu, 0x02423C00u), // 51 3
        uvec2(0x040C1424u, 0x7E040400u), // 52 4
        uvec2(0x7E407C02u, 0x02423C00u), // 53 5
        uvec2(0x3C42407Cu, 0x42423C00u), // 54 6
        uvec2(0x7E020408u, 0x10202000u), // 55 7
        uvec2(0x3C42423Cu, 0x42423C00u), // 56 8
        uvec2(0x3C42423Eu, 0x02423C00u), // 57 9
        uvec2(0x00181800u, 0x00181800u), // 58 :
        uvec2(0x00000000u, 0x00000000u), // 59 ;
        uvec2(0x00000000u, 0x00000000u), // 60 <
        uvec2(0x00000000u, 0x00000000u), // 61 =
        uvec2(0x00000000u, 0x00000000u), // 62 >
        uvec2(0x78840408u, 0x10001000u), // 63 ?
        uvec2(0x00000000u, 0x00000000u), // 64 @
        uvec2(0x18244242u, 0x7E424200u), // 65 A
        uvec2(0x7C42427Cu, 0x42427C00u), // 66 B
        uvec2(0x3C424040u, 0x40423C00u), // 67 C
        uvec2(0x78444242u, 0x44447800u), // 68 D
        uvec2(0x7E40407Cu, 0x40407E00u), // 69 E
        uvec2(0x7E40407Cu, 0x40404000u), // 70 F
        uvec2(0x3C42404Eu, 0x42423C00u), // 71 G
        uvec2(0x42427E42u, 0x42424200u), // 72 H
        uvec2(0x3C181818u, 0x18183C00u), // 73 I
        uvec2(0x1E0C0C0Cu, 0x4C4C3800u), // 74 J
        uvec2(0x42444870u, 0x48444200u), // 75 K
        uvec2(0x40404040u, 0x40407E00u), // 76 L
        uvec2(0x42665A5Au, 0x42424200u), // 77 M
        uvec2(0x42625246u, 0x42424200u), // 78 N
        uvec2(0x3C424242u, 0x42423C00u), // 79 O
        uvec2(0x7C42427Cu, 0x40404000u), // 80 P
        uvec2(0x3C42424Au, 0x44443A00u), // 81 Q
        uvec2(0x7C42427Cu, 0x48444200u), // 82 R
        uvec2(0x3C42403Cu, 0x02423C00u), // 83 S
        uvec2(0x7E181818u, 0x18181800u), // 84 T
        uvec2(0x42424242u, 0x42423C00u), // 85 U
        uvec2(0x42424242u, 0x24241800u), // 86 V
        uvec2(0x42425A5Au, 0x66424200u), // 87 W
        uvec2(0x42422418u, 0x24424200u), // 88 X
        uvec2(0x42422418u, 0x18181800u), // 89 Y
        uvec2(0x7E040810u, 0x20407E00u), // 90 Z
        uvec2(0x00000000u, 0x00000000u), // 91 [
        uvec2(0x00000000u, 0x00000000u), // 92 backslash
        uvec2(0x00000000u, 0x00000000u), // 93 ]
        uvec2(0x00000000u, 0x00000000u), // 94 ^
        uvec2(0x00000000u, 0x00000000u), // 95 _
        uvec2(0x00000000u, 0x00000000u), // 96 `
        uvec2(0x00000000u, 0x00000000u), // 97-127 vuoti
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u),
        uvec2(0x00000000u, 0x00000000u)
    );
    if (code < 32 || code > 127) code = 63; // '?' fuori range
    return F[code - 32];
}

/// @fn textChar
/// carattere i-esimo del testo da uText (ASCII, 0 se oltre uTextLen).
int textChar(int i) {
    if (i < 0 || i >= uTextLen) return 32;
    uint w = uint(uText[i >> 2]);
    return int((w >> (8u * uint(i & 3))) & 0xFFu);
}

/// @fn drawGlyph
/// copertura 0..1 di un carattere ASCII `code` in coordinate pixel (y verso l'alto, come fragCoord):
/// origin = angolo basso-sx del glifo, scale = dimensione glifo (8*scale px). Per scritte proprie
/// (es. "HI!": drawGlyph(p, o, 1.0, 72) + drawGlyph(p, o + vec2(8, 0), 1.0, 73) + ...).
float drawGlyph(vec2 fragPx, vec2 origin, float scale, int code) {
    vec2 rel = (fragPx - origin) / scale;
    if (rel.x < 0.0 || rel.y < 0.0 || rel.x >= 8.0 || rel.y >= 8.0) return 0.0;
    uvec2 g = fontGlyph(code);
    int col = int(rel.x);
    int row = 7 - int(rel.y);  // la riga 0 del font è quella in alto
    uint bits = (row < 4) ? (g.x >> (8u * uint(3 - row))) : (g.y >> (8u * uint(7 - row)));
    return float((bits >> (7u - uint(col))) & 1u);
}

/// @fn drawText
/// copertura 0..1 del testo (da uText) disegnato in coordinate pixel (y verso l'alto, come fragCoord):
/// origin = angolo basso-sx del primo glifo, scale = dimensione glifo (8*scale px).
/// Ritorna 1 dove il testo copre il pixel.
float drawText(vec2 fragPx, vec2 origin, float scale) {
    vec2 rel = (fragPx - origin) / scale;
    if (rel.x < 0.0 || rel.y < 0.0) return 0.0;
    int ci = int(rel.x / 8.0);
    if (ci >= uTextLen || rel.y >= 8.0) return 0.0;
    return drawGlyph(fragPx, origin + vec2(float(ci) * 8.0 * scale, 0.0), scale, textChar(ci));
}
