# Termo Solar

Integración de Home Assistant que decide **cuándo calentar un termo
eléctrico** en una casa con placas solares, batería y tarifa con periodos
(Punta / Llano / Valle). Sustituye a un puñado de automatizaciones y
ayudantes por un solo dispositivo que, además, **explica cada decisión**.

La idea: que a la hora de la ducha haya agua caliente, gastando primero el
sol que sobra, después el Valle y nunca la Punta.

## Qué hace

Cada 30 segundos mira cómo está el agua y elige, por este orden:

1. **Sol.** Si a las placas les sobra potencia para el termo entero durante
   2 minutos, lo enciende. Lo apaga si el sol falta 3 minutos (una nube no
   lo apaga y lo enciende sin parar). Calienta hasta la *temperatura
   objetivo*; si además la batería está llena —ese sol se iba a exportar—,
   sigue hasta la *temperatura máxima con sol*.
2. **Valle.** Los días laborables, en las horas previas al fin del Valle,
   mira la previsión solar del día. Si **no va a sobrar sol** (previsión
   prudente − lo que gasta la casa de día − lo que le cabe a la batería <
   lo que pide el termo), calienta en Valle, **lo más tarde posible** para
   que el agua llegue caliente a la tarde. Si va a sobrar, espera al sol.
3. **Respaldo.** A la *hora del respaldo*, si a la *hora de la ducha* el
   agua no va a llegar a la *temperatura mínima*, calienta con lo que haya
   (red o batería) hasta el objetivo. **Nunca en Punta.** Cubre los días en
   que la previsión falló, los festivos sin sol y un gasto fuerte de agua a
   media tarde.

Y siempre:

- **No pasa de la potencia contratada**: si con el termo se va a pasar,
  espera; si ya está encendido y la casa sube, lo pausa y vuelve cuando cabe.
- **Sin sonda no calienta**, y si la sonda lleva una hora sin moverse con
  el termo encendido la da por atascada y para.
- **Sin red eléctrica** (corte de luz) no enciende.
- Un **encendido a mano** se respeta hasta la temperatura máxima.

## Simulación primero

Recién instalada **no toca el termo**: el interruptor «Control» está
apagado y la integración solo calcula. `binary_sensor.termo_solar_orden`
dice lo que mandaría y `sensor.termo_solar_motivo` por qué; compáralos unos
días con lo que hace tu sistema actual. Cuando te convenza, desactiva tus
automatizaciones del termo y enciende «Control».

## Entidades

| Entidad | Qué es |
|---|---|
| `sensor.termo_solar_estado` | Esperando / Calentando con sol / en Valle / respaldo / a mano / en pausa por potencia / sin datos / sonda atascada |
| `sensor.termo_solar_motivo` | La explicación, en una frase |
| `binary_sensor.termo_solar_orden` | Lo que manda (o mandaría) al termo |
| `sensor.termo_solar_energia_necesaria` | kWh que faltan hasta el objetivo |
| `sensor.termo_solar_temperatura_ducha` | Temperatura prevista a la hora de la ducha si no se calienta |
| `sensor.termo_solar_excedente` | W que sobran de las placas sin contar el termo |
| `sensor.termo_solar_sol_sobrante` | kWh de sol que van a sobrar hoy (negativo: no sobra); el desglose, en sus atributos |
| `sensor.termo_solar_energia_hoy` | kWh que ha gastado hoy el termo, y con qué fuente |
| `sensor.termo_solar_kwh_por_grado` | Aprendido de cada calentado |
| `sensor.termo_solar_consumo_casa` | Consumo de la casa de día, aprendido hora a hora |
| `switch.termo_solar_control` | Encendido: manda. Apagado: simula |
| `number.termo_solar_objetivo` | Temperatura objetivo (51 °C) |
| `number.termo_solar_maxima_solar` | Temperatura máxima con sol sobrante (60 °C) |
| `number.termo_solar_minima_ducha` | Temperatura mínima a la hora de la ducha (42 °C) |
| `number.termo_solar_potencia` | Potencia del termo (1700 W) |
| `number.termo_solar_margen_prevision` | Cuánto se le quita a la previsión solar (15 %) |
| `time.termo_solar_hora_ducha` | Hora de la ducha (19:00) |
| `time.termo_solar_hora_respaldo` | Hora del respaldo (16:00) |
| `time.termo_solar_fin_valle` | Fin del Valle en laborables (08:00) |

## Qué necesita

Obligatorio: el interruptor del termo, una sonda de temperatura del agua,
la potencia de las placas, el consumo de la casa y un sensor con el periodo
tarifario (`Punta` / `Llano` / `Valle` o `P1` / `P2` / `P3`).

Opcional: un sensor de día laborable, la previsión de
[Solcast](https://github.com/BJReplay/ha-solcast-solar) («Pronóstico hoy»),
la carga de la batería y su capacidad, la potencia de la red con la
potencia contratada, y un sensor de «hay red».

El termostato del propio termo tiene que estar **por encima** de la
temperatura máxima con sol: es el seguro si Home Assistant se para con el
termo encendido.

## Instalación

HACS → ⋮ → Repositorios personalizados → esta URL, categoría Integración.
Instalar, reiniciar Home Assistant y añadir «Termo Solar» en Ajustes →
Dispositivos y servicios.

El porqué de cada decisión está en [docs/DECISIONES.md](docs/DECISIONES.md).
