"""Icono de Termo Solar: un termo con un sol, en blanco sobre un cuadrado
redondeado naranja.

    /tmp/hav/bin/python docs/icono/generar.py custom_components/termo_solar/brand
"""
import math
import sys

from PIL import Image, ImageDraw


def dibujar(lado: int) -> Image.Image:
    S = 4  # sobremuestreo para bordes suaves
    W = lado * S
    u = W / 256  # unidades de un lienzo de 256

    fondo = Image.new("RGBA", (W, W))
    arriba, abajo = (255, 183, 77), (230, 81, 0)
    df = ImageDraw.Draw(fondo)
    for y in range(W):
        t = y / (W - 1)
        df.line([(0, y), (W, y)], fill=tuple(round(arriba[i] + (abajo[i] - arriba[i]) * t) for i in range(3)) + (255,))
    mascara = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mascara).rounded_rectangle([0, 0, W - 1, W - 1], radius=56 * u, fill=255)
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    img.paste(fondo, (0, 0), mascara)

    capa = Image.new("L", (W, W), 0)
    d = ImageDraw.Draw(capa)

    # Termo: depósito vertical con contorno grueso y dos tomas abajo.
    d.rounded_rectangle([58 * u, 70 * u, 150 * u, 206 * u], radius=30 * u, outline=255, width=round(13 * u))
    for x in (82, 126):
        d.rounded_rectangle([(x - 6) * u, 204 * u, (x + 6) * u, 228 * u], radius=4 * u, fill=255)
    # Nivel de agua caliente: tres ondas.
    for y in (116, 142, 168):
        d.rounded_rectangle([82 * u, (y - 5) * u, 126 * u, (y + 5) * u], radius=5 * u, fill=255)

    # Sol arriba a la derecha.
    cx, cy, r = 186 * u, 70 * u, 24 * u
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    for k in range(8):
        a = math.radians(45 * k)
        d.line(
            [cx + math.cos(a) * 33 * u, cy + math.sin(a) * 33 * u, cx + math.cos(a) * 46 * u, cy + math.sin(a) * 46 * u],
            fill=255, width=round(9 * u),
        )

    blanco = Image.new("RGBA", (W, W), (255, 255, 255, 255))
    img.paste(blanco, (0, 0), capa)
    return img.resize((lado, lado), Image.LANCZOS)


destino = sys.argv[1]
dibujar(256).save(f"{destino}/icon.png", optimize=True)
dibujar(512).save(f"{destino}/icon@2x.png", optimize=True)
print("ok")
