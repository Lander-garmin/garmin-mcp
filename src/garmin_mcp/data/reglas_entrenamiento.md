# Reglas de entrenamiento de Lander (fuente única)

Este archivo es la ÚNICA fuente de reglas. Lo devuelve la herramienta `get_training_rules`
del conector Sync EU. Las correcciones de Lander prevalecen sobre cualquier dato histórico,
plantilla existente o entreno anterior de Garmin: nunca copies una plantilla vieja.

## Atleta
- Lander, 22 años, 70 kg, 174 cm. Corredor (medio maratón 1:42), pulso en reposo base 42-46.
- También hace gimnasio y bici. Objetivos: mucho volumen aeróbico, perder peso y progresar en
  fuerza sin ganar volumen de pierna. Reparto de intensidad 80/20.
- Reloj: Forerunner 55. La fuerza se hace con la app "Pesas" del reloj, que carga el entreno de
  fuerza programado para hoy en el calendario de Garmin.

## Calendario semanal (se alternan semana A y semana B)
La letra de la semana la calcula `get_training_rules` (19-25/10/2026 = B; después alternan).

| Día | Hora | Sesión |
|---|---|---|
| L | — | Descanso total. Nunca se programa nada. |
| M | 17:30 | Pesas Pull + rodaje de 12 km justo después, por pulso: media ≤145 ppm, sin objetivo de ritmo |
| X | 17:30 | Semana A: Pesas Legs · Semana B: Pesas Hyrox |
| J | 17:30 | Pesas Push |
| V | 18:30 | Series: 20' calentamiento + 5x1000 a 4:05-4:15 con 2' de recuperación + 10' vuelta a la calma (~10 km) |
| S | 10:00 | Bici larga 2 h 30 a 119-139 ppm |
| D | 10:00 | Tirada larga de 18 km por pulso: media 145-155 ppm, nunca por encima de 159, sin objetivo de ritmo |

- Nombres en el calendario: "Plan <letra día> <dd/mm> <descripción>". Ejemplo:
  "Plan X 21/10 Pesas Hyrox 55 min". Las sesiones de fuerza llevan SIEMPRE la palabra "Pesas".
- Legs nunca la víspera de las series ni de la tirada larga. Nunca dos días duros seguidos.

## Reglas de fuerza (todas las sesiones)
- Como máximo 6 bloques y unos 60-65 min.
- Primer ejercicio: 1 serie de calentamiento a peso ligero + 3 series de trabajo. Resto de
  ejercicios: 3 series. Sin include_warmup.
- Descanso de 180 s en todos los ejercicios, con cuenta atrás.
- exercise_name y category en inglés (enum de Garmin). La nota empieza por el nombre en
  castellano y sigue con el objetivo de progresión.
- Pesos en kg.
- Las correcciones de Lander prevalecen sobre cualquier dato histórico o plantilla existente.

### PULL (pesos de partida)
1. Chin Up (dominada SIN goma) x12. Lastre cuando haga 3x12 limpias.
2. Barbell Bent Over Row 82,5 kg x12.
3. Straight Arm Pulldown 34 kg x12.
4. Hiperextensión con disco de 20 kg x20.
5. Dumbbell Hammer Curl 28 kg x12.
6. SUPERSERIE: Toes To Bar x15 + Crunch x12 (descanso solo tras el bloque).

### PUSH (pesos de partida)
1. Barbell Bench Press 75 kg x8. No priorizar pecho.
2. SUPERSERIE: Seated Dumbbell Shoulder Press 44 kg x12 + Plate Front Raise 10 kg x12.
3. Cable Crossover 30 kg x12.
4. SUPERSERIE (doble serie): Triceps Pressdown 22,5 kg x12 -> directo 15 kg x10.
5. Dumbbell Lateral Raise 14 kg x20.
6. Face Pull 35 kg x12.

### LEGS (semana A)
1. Barbell Back Squat 80 kg x8. Peso FIJO, no se sube.
2. Dumbbell Walking Lunge 17 kg x12.
3. Hiperextensión con disco de 20 kg x20.
4. Seated Calf Raise 20 kg x12.
5. Hip Abduction Machine 60 kg x15. Solo abducción, SIN aducción.
6. Sled Push 3x60 s con 110 kg totales (trineo + discos) y cuenta atrás.

### HYROX (semana B, unos 55 min)
- 10' de calentamiento.
- 3 rondas, 2' de descanso entre rondas: 1 km en cinta a ~4:45 -> 500 m SkiErg -> Sled Push 60 s
  (mismo peso y progresión que en Legs) -> 500 m remo -> 20 zancadas con mancuernas de 10 kg ->
  30 wall balls de 6 kg.

## Cómo se escribe cada entreno en el conector (obligatorio)
Fuerza: `preview_strength_workout` -> revisar -> `create_strength_workout` con el token ->
`schedule_workout`. En cada ejercicio:
- `name` en inglés, `exercise_name` + `category` explícitos (tabla abajo), `display_name` en
  castellano (máx. 22 caracteres, es lo que se ve en el reloj) y `note` con el objetivo.
- Pesos con `weight` en kg (`weight_unit` "kg"; es el valor por defecto). Nunca libras.
- Calentamiento: en el PRIMER bloque, campo `warmup: {reps, weight}` (peso ligero). No uses
  `include_warmup`.
- `rest_seconds: 180` en todos los bloques de fuerza (Hyrox: 120 entre rondas).
- Superserie = varios ejercicios en el MISMO bloque (el descanso va solo al final del bloque).
  La doble serie de tríceps es un bloque con dos ejercicios Triceps Pressdown (22,5 x12 y 15 x10).
- Sled Push: `seconds: 60` + `weight` (serie por tiempo con peso; el reloj cuenta atrás y la
  cierra solo). Nunca reps.
- Hyrox: un bloque de `sets: 3` con los 6 pasos y `rest_seconds: 120`, más un bloque previo de
  calentamiento de 10' (Treadmill `seconds: 600`). Distancias con `meters`.
- El preview no debe mostrar avisos (warnings). Si los hay, corrige antes de crear.

| Ejercicio | category | exercise_name | display_name |
|---|---|---|---|
| Dominada | PULL_UP | CHIN_UP | Dominada |
| Remo con barra | ROW | BENT_OVER_ROW_WITH_BARBELL | Remo con barra |
| Jalón brazos rectos | PULL_UP | STRAIGHT_ARM_PULLDOWN | Jalon brazos rectos |
| Hiperextensión | HYPEREXTENSION | HYPEREXTENSION | Hiperextension |
| Curl martillo | CURL | DUMBBELL_HAMMER_CURL | Curl martillo |
| Pies a barra | CRUNCH | TOES_TO_BAR | Pies a barra |
| Abdominal corto | CRUNCH | CRUNCH | Abdominal corto |
| Press banca | BENCH_PRESS | BARBELL_BENCH_PRESS | Press banca |
| Press hombro mancuernas | SHOULDER_PRESS | SEATED_DUMBBELL_SHOULDER_PRESS | Press hombro manc. |
| Elevación frontal disco | SHOULDER_PRESS | WEIGHT_PLATE_FRONT_RAISE | Elev. frontal disco |
| Cruce de poleas | FLYE | CABLE_CROSSOVER | Cruce de poleas |
| Tríceps polea | TRICEPS_EXTENSION | TRICEPS_PRESSDOWN | Triceps polea |
| Elevaciones laterales | LATERAL_RAISE | DUMBBELL_LATERAL_RAISE | Elev. laterales |
| Face pull | ROW | FACE_PULL | Face pull |
| Sentadilla | SQUAT | BARBELL_BACK_SQUAT | Sentadilla |
| Zancadas mancuernas | LUNGE | WALKING_DUMBBELL_LUNGE | Zancadas manc. |
| Gemelo sentado | CALF_RAISE | SEATED_CALF_RAISE | Gemelo sentado |
| Abducción de cadera | HIP_STABILITY | STANDING_HIP_ABDUCTION | Abduccion cadera |
| Empuje de trineo | SLED | PUSH | Empuje trineo |
| Cinta | RUN_INDOOR | TREADMILL | Cinta |
| SkiErg | CHOP | CHOP | SkiErg |
| Remo ergómetro | ROW | INDOOR_ROW | Remo ergometro |
| Wall balls | SQUAT | WALL_BALL | Wall balls |

Carrera: `preview_running_workout` / `create_running_workout`:
- Rodaje: paso por distancia (`distance_meters`), `hr_min_bpm: 119`, `hr_max_bpm: 145`, sin ritmo.
- Tirada larga: paso por distancia (`distance_meters`), `hr_min_bpm: 145`, `hr_max_bpm: 155`, sin
  ritmo. La nota indica "máximo 159".
- Series: por ritmo, como ahora.

Bici:
`preview_cycling_workout` / `create_cycling_workout` con pasos por tiempo y 119-139 ppm.

## Revisión semanal de entrenador (cada domingo, antes de crear la semana siguiente)
QUÉ REVISAR:
- Carrera: ritmo por km, pulso medio y máximo, deriva de pulso, tiempo en zonas, pulso en las
  recuperaciones de las series, y la sensación (`feel`) y el RPE (`rpe`) que Lander puso en el reloj.
- Fuerza: reps y kg hechos frente a los planificados (`get_strength_sets`), y series completadas
  o fallidas. La sensación y el RPE de la app Pesas también están en la actividad.
- Bici y Hyrox: duración, pulso y tiempo en zonas.
- Recuperación: pulso en reposo frente a su base de 42-46, sueño y Body Battery.

REGLAS DE DECISIÓN (sube / mantiene / baja):
- Fuerza:
  - Todas las series completas con las reps objetivo -> +2,5 kg la semana siguiente.
  - Falla reps -> mantiene.
  - Falla dos semanas seguidas -> baja un 10 %.
  - Excepciones: sentadilla fija en 80 kg; trineo +10 kg solo si completa los 60 s sin parar
    (tope 152 kg); dominadas, lastre solo tras 3x12 limpias.
- Rodaje:
  - Pulso medio <= 145 -> +1 km la semana siguiente, hasta un tope de 14 km.
  - Pulso medio por encima de 145 -> misma distancia y aviso.
- Bici:
  - Pulso medio <= 139 -> se mantiene o sube volumen.
  - Pulso por encima de 139 -> misma duración y aviso de bajar el ritmo.
- Series:
  - Ritmo en objetivo, pulso de recuperación por debajo de 150 y RPE <= 8 -> progresa
    (5x1000 o 4:00-4:05).
  - Si no se cumple -> repite la misma sesión.
- Tirada larga:
  - Pulso medio <= 155, máximo <= 159 y RPE <= 6 -> +1-2 km, hasta 21 km.
  - Si no se cumple -> se repite.
  - Una vez al mes (último domingo del mes) la tirada es un medio maratón completo (21,1 km) con
    las mismas condiciones de pulso. Excepción: el domingo 25/10/2026 (semana base) lleva 18 km;
    el primer medio maratón es el 29/11/2026.
- Volumen de carrera: la semana del 19-25/10/2026 es la semana base, con unos 40 km. Desde ahí,
  como máximo +10 % por semana.
- Pulso en reposo 3 o más ppm por encima de la base durante 2 días, o RPE alto en sesiones
  suaves -> semana de mantenimiento o descarga, sin subir nada.
- Si falta la valoración del reloj en una sesión, decide solo con datos objetivos y señálalo.

SALIDA EN EL INFORME SEMANAL:
- Una tabla: sesión -> decisión (sube / mantiene / baja) -> motivo en una línea con el dato que
  la justifica.
- Esas decisiones se aplican en los entrenos que se crean para la semana siguiente.

## Restricciones
- Solo la tarea del domingo crea entrenos. Las diarias solo leen.
- Un cambio entre semana se hace sustituyendo la plantilla (borrar la vieja y crear la nueva),
  nunca añadiendo otra.
- Todas las escrituras en Garmin pasan por preview + confirmation_token.
