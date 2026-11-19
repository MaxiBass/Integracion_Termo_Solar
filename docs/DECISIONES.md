# Decisiones de diseño

## 1. Para qué

En casa del autor el termo lo llevaban ocho automatizaciones, cuatro
ayudantes y tres plantillas. Funcionaba, pero una de las piezas (la que
calentaba en Valle si no iba a haber sol) estuvo meses sin actuar por una
mezcla de unidades y nadie lo notó: no hay una entidad que diga «hoy he
decidido esto por esto».

Esta integración es lo mismo en una sola pieza, con pruebas y con la
explicación a la vista. **No busca ahorrar más**: medido con un mes de
datos reales, entre la mejor y la peor forma de calentar el termo hay pocos
euros al mes. Busca que haya agua caliente siempre y que, si algo falla, se
vea.

Queda fuera, a propósito, decidir la carga de la batería desde la red: con
los programas horarios del inversor ya casi no se importa fuera del Valle.

## 2. Tres fuentes, en este orden

**Sol → Valle → respaldo de la tarde.** Y no hay «una vez al día»: cada
decisión mira la temperatura del agua. Si a media tarde alguien gasta el
depósito, el respaldo lo ve y recalienta; con un contador de «ya he
calentado hoy», no.

El respaldo no elige fuente: enciende, y el inversor dará red o batería
según sus programas. Lo único que la integración se niega a hacer es
empezar o seguir en **Punta**.

Los festivos (día no laborable) no se calienta de madrugada: todo el día
es Valle, así que se espera al sol y, si no llega, el respaldo completa por
la tarde al mismo precio y sabiendo ya lo que ha pasado.

## 3. Umbrales

| Qué | Valor | Por qué |
|---|---|---|
| Excedente para encender | la potencia del termo, 2 min | que el termo entero salga del sol |
| Excedente para apagar | potencia − 300 W, 3 min | las nubes pasan; 300 W de la batería se toleran |
| Mínimo encendido / apagado con sol | 5 min | el relé y el termo no son un intermitente |
| Histéresis | 3 °C | no recalentar por un grado |
| Batería «llena» | 97 % | a partir de ahí el excedente se exporta |
| ICP | > 1,1 × contratada 10 min, o > 1,5 × al instante; vuelve tras 2 min cabiendo | igual que la automatización anterior, que estaba decidida así |
| Sonda atascada | 1 h encendido sin cambiar | igual que la automatización anterior |
| Sonda sin dato | se sigue 5 min con el último valor | una reconexión de Zigbee no debe apagar y encender el termo |
| Ventana del Valle | 4 h antes de su fin | decidir con la previsión más reciente |
| Pérdidas | 1,8 % por hora de (T − 22 °C) | medido: 0,5 °C/h a 50 °C |

El excedente se calcula como placas − (consumo − termo si está encendido):
así el propio termo no se cuenta como consumo de la casa y el umbral de
encender y el de apagar son comparables.

## 4. ¿Va a sobrar sol hoy?

En invierno casi ningún día se exporta: cada kWh de sol que se lleva el
termo deja de ir a la batería, y esa energía se acaba comprando más cara.
Por eso «hay sol» no basta; tiene que **sobrar**:

    sol previsto × (1 − margen)
      − consumo de la casa en las horas de sol
      − lo que le cabe a la batería
      − lo que pide el termo            ≥ 0

y además tiene que haber **potencia**: medias horas, antes de la hora del
respaldo, en las que el sol previsto menos la casa cubra el termo entero,
suficientes para calentarlo. Si falla cualquiera de las dos, Valle. Sin
previsión, también Valle.

Contrastado con 31 días reales (octubre–noviembre): acierta 23 de los 24
días en que la respuesta estaba clara, y el fallo es de los baratos (dijo
«Valle» un día que sobró: unos céntimos). La regla anterior, con un margen
fijo en vez del consumo real, acertaba 21 y sus 3 fallos eran de los caros
(dijo «sol» y no sobró).

El margen del 15 % sale de ahí: la previsión se pasa más veces de las que
se queda corta, sobre todo los días malos.

## 5. Lo que aprende

- **kWh por grado**: de cada calentado real de al menos 10 min y 5 °C
  (potencia × tiempo ÷ grados), con media móvil (peso 0,2). Empieza en
  0,09 (≈ un termo de 80 L).
- **Consumo de la casa sin el termo**, media de cada hora, laborables
  aparte de festivos, con la misma media móvil. Donde aún no ha aprendido,
  400 W.

Las dos cosas se aprenden también en simulación, mirando el interruptor
real. Se guardan en `.storage/termo_solar` junto con la memoria de la
decisión, así que un reinicio a mitad de un calentado no lo corta.

## 6. Simulación y control

«Control» apagado (por defecto): no se manda nada. La decisión se calcula
igual; solo cambia que no hay modo «manual» (el termo lo llevan otros).

«Control» encendido: la integración pone el interruptor como diga la
decisión y lo repite si no coincide (un relé Zigbee que vuelve de «no
disponible» encendido se apaga). Excepción: si alguien lo enciende a mano
—un paso de apagado a encendido que la integración no ha pedido—, se
respeta hasta la temperatura máxima.

Al apagar «Control» se apaga el termo si lo había encendido la integración:
nadie más lo iba a apagar.

## 7. Una sola temperatura que tocar

El autor ajusta a mano la temperatura del agua según la época del año, en
un ayudante que ya usaban sus automatizaciones. Por eso:

- Si en el alta se indica ese **ayudante**, el objetivo es el suyo. No hay
  dos sitios donde cambiarlo: `number.termo_solar_objetivo` lo refleja (con
  sus límites) y, si se cambia ahí, se escribe en el ayudante. Si el
  ayudante deja de estar disponible, se sigue con su último valor.
- La temperatura máxima con sol y la mínima de la ducha no son valores
  fijos sino **grados respecto al objetivo** (+9 y −9 por defecto). Con
  valores fijos, al bajar el objetivo en verano la mínima de la ducha
  quedaría por encima de él y el respaldo saltaría todas las tardes.

## 8. Entidades

`entity_id` fijos (`sensor.termo_solar_estado`…), para que paneles e
historial no dependan de cómo se llame el dispositivo. Los ajustes del día
a día son entidades (`number`, `time`, `switch`) y se guardan en las
opciones de la entrada sin recargar; las entidades de origen se cambian en
Configurar.

## 9. Pendiente

- Aprender también la potencia del termo y las pérdidas.
- Avisar (notificación) cuando el respaldo no llega a tiempo o la sonda se
  atasca; hoy solo se ve en el estado.
