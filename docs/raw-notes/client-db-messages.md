## Explanation from the client about how the Database work

Databse: OrbitMedia_Test

This is a SQL Server database that was mode for me to test on.

### Text messages:

Him: claro las tabla principales por asi decirlo dos SPOTS2(es la tabla donde se guardan los comerciales para radio y SPOTS_TV( lo mismo pero para tv) en estos se enlazan con la tabla de  COMERCIALES y tienen el horario en el que fue emitido el comercial,  en esta tabla de comerciales donde se almacenan todos los spots de tv y radio tambien se enlaza con la tabla de anunciantes y marcas, las otras tablas clave son TESTIGO_SARA y SEGMENTO_SARA estas se relacionan mucho entre si porque el TESTIGO_SARA hace referencia al audio de 2 horas de una estacion y los segmentos dentro de esas dos horas que se reconozcan como comerciales se almacenan en SEGMENTO_SARA asi que un testigo tiene muchos segmentos y de ahi pasan por otro proceso para convertirse en SPOTS ya sea de tv o radio

ME: Entonces en SPOTS_2 y SPOTS_TV se almacenan los spots publicitarios de radio y television, y TESTIGO_SARA almacena los espacios de 2 horas de programa, que tras ser procesados pasan a SEGMENTO_SARA y de ahi a SPOTS_TV o SPOTS_2, dependiendo del caso?

him: asi es. y en la tabla de comerciales ahi se almacena solo una ves el comercial con los datos del anunciantes y la marca y en los spots ya te indica realmente cuantas veces salio ese comercial al dia

Him: tambien como dato La tabla MARCAS hace referencia a los anunciantes y la tabla ANUNCIANTES hace referencia a las marcas, porque pasa esto? asi se dieron de alta esas tablas desde el principio y ahorita ya es muy complicado cambiarlas por el volumen de informacion

Me: Los archivos de audio como los que me compartieron donde están guardados? Para diseñar la forma en que serian jalados desde el servidor para ser procesado

Him: es en esta ruta C:\Sara\mp3 tambien deja una manera de cambiar la ruta o solo la letra de la unidad de disco duro porque en algunos equipos se maneja el disco D. tambien te di acceso a dos store procedure uno es SaraOpGrabaFP y el otro es SaraOpGrabaComercial estos se utilizan para guardar el alta de un nuevo comercial no identificado o su segunda version

Me: Okay, y para acceder a esos?

Him: en la misma base de datos de prueba te di permisos para esos stores

Me: Una pregunta, para la herramienta uno, solamente se tienen que analizar los segmentos que dicen "Por clasificar", cierto?

Him: bueno el segmento aparece con la leyenda sin identificar

Me: En el archivo BD Monitoreo - Radio Monterrey - 15 Ago 26.xlsx que me compartieron no viene nada de Sin Identificar. Si viene asi? Veo muchos que dicen por clasificar, supose que era eso?

Him: a ya vi esa base de datos es de los comerciales (VERSION) que es la estructura que manejamos ahi pues esl resultado de un reporte ya trabajado donde puedes observar los comerciales minuto a minuto de una estacion de radio, donde estos comerciales ya cuentan con una categoria, anunciante  y marca asignada, los que aparecen por clasificar es simplemente que no esta dado de alta un anunciante para ese comercial

Him: mira te mando un ejemplo asi es como se ve el analisis de comercial en un testigo(fragmento de audio de emisora de 2 horas) ahi se puede observar los comerciales(version) que reconocio y los que no, con el estatus de nuevo sin identificar, esos son los que se tiene que revisar y analisas si hay un comercial nuevo o no (SegmentosDelTestigo21332242.csv file)

Me: Perfecto jeje, por que justo esa era la duda que tenia

Him: muy bien justo vas a tener que trabajar mas de la mano con la tabla de SEGMENTO_SARA y ANUNCIANTE

Me: Porque justo estaba trabajando en la implementacion ya con la base de datos y eso no me cuadraba con lo que tenia. Porque todo lo de transcripcion, segmentacion y clasificacion ya lo tengo funcional, solo es asegurarme que lo que se va a procesar sea el correcto

Him: select * from TESTIGO_SARA where ID_ESTATUS_TESTIGO=3 order by FECHA_INICIO desc tambien esta consulta te ayudara a buscar los testigos que ya tiene segmentos reconocidos ese es el estatus 3 y con este store procedura puedes ver los segmentos de un testigo saraOpObtieneSegmentos

Him: Hola buenos tardes, para comentarte acerca de las herramientas, porque hubo algunas actualizaciones en los requerimientos y la verdad facilitan un poco mas la ejecución, Por ej. la herramienta 1:en esta herramienta se requiere transcribir archivos .wav recortados previamente, (ya no ocupariamos recortar),pero si analizar los spots que se repitan mas de una vez(tampoco se tomarían en cuenta los spots que ya se registraron en la base de datos alguna ves), esos spots que aparecen mas de una ves se registrarían en una tabla, puede ser nueva o ocupar la misma ALTAS_SARA_FP pero tendria un estatus de "Pendiente de Validación" o algo similar, donde luego un capturista pudiera validar ese spots como nuevo, mostrandole el titulo, transcripcion, el anunciante que tiene asignado etc (de esta parte donde el capturista valida no te preocupes, con que se pueda ver el titulo, transcripcion y otros datos que se requieren para dar de alta esta super bien, yo me encargo de que el capturista la valide ).

Him: con la herramienta dos: no cambia casi nada a lo que comentas en si es identificar menciones de marcas en los segmentos, pero seria en los segmentos descartados (ya sea descartado por canción o por operados) y los segmentos muy grandes y no con los segmentos nuevos sin identificar(esto lo haria  la herramienta uno junto a nuestros procesos) y de igual forma se registraría un titulo, anunciante, hora en la cual empezo a mencionarse la marca y la hora fin y de igual manera se guardaria en una tabla donde este sujeta a validación

Me: A que te refieres con analizar los spots que se repiten mas de una vez?

Him: Ok en realidad es a guardar esos spots en la tabla donde se procederán a validar por un capturista

Me: Ok, entonces no le hago nada a esos segmentos que se repiten? Solo los guardo?

Him: Así es, estos ya están recortados lo que les faltaría sería asignarles un título, anunciante, duración, inicio etc

Him: También no todos los recortes se van a analizar solo los que tengan el estatus de pendiente de  autorización

Me: ok, que numero de estatus es ese?

Him: Es el 4 viene en la tabla de ALTAS_SARA_FP en el campo de id_estatus_alta

Him: Deja te explico brevemente 1 nuevo es el estatus qué tiene cuando recién se recortan las altas gracias a un programa, 2 recortado indica que estos recortes pasaron a ser manejados por el programa reconoce los spots como ya identificados y solo deja a los que no se han identificado

Him: 3 es error, 4 son los recortes qué le aparecen a los capturistas para que puedan capturarlos 5 son los que detecto como spots qué ya estaban dados de alta en la BD y 7 es que el recorte se ha dado de alta exitosamente y se convertirá en un spot

Me: Entonces busco los que tengan status 4

Me: El acceso que me compartiste es para la base de datos solamente, creo

Me: Lo que estaba buscando es poder validar las herramientas desarrolladas con un flujo un poco mas real, tomando los archivos como se van identificando o no por sus programas

Me: Porque esto que tengo es todo el programa de cada hora para un dia, pero tengo entendido que las herramientas recibirian ya los archivos de las porciones donde no ha sido identificado

Him: Así es en base a la tabla de ALTAS_SARA_FP ahí podrías darte cuenta cuales ya se ha identificado y cuales no, esto para la herramienta 1

Him: Aparte de los wav recortados qué otra cosa te hace falta?

Me: creo que eso seria todo

Me : Super, muchas gracias. En lo que conseguimos los wav recortados estare usando los archivos que me compartieron y usando lo que viene en ALTAS_SARA_FP para poder saber cuales son los espacios no identificados y recortarlos yo, te parece?
