# coding=utf-8

"""	Permite crear una instancia que se encargara de proporcionar funciones
	facilitando el manejo del modem. Entre las funcionalidades basicas con
	las que cuenta, tenemos principalmente el envio y recepcion de mensajes
	SMS.
	@author: Gonzalez Leonardo Mauricio
	@author: Reinoso Ever Denis
	@organization: UNC - Fcefyn
	@date: Miercoles 17 de Junio de 2015 """

import os
import time
import shlex
import Queue
import serial
import signal
import inspect
import subprocess
import commentjson

import logger
import errorList
import contactList

from curses import ascii # Para enviar el Ctrl-Z

JSON_FILE = 'config.json'
JSON_CONFIG = commentjson.load(open(JSON_FILE))

class Modem(object):
	""" Clase 'Modem'. Permite la creacion de una instancia del dispositivo. """
	atError = False
	modemOutput = None

	def __init__(self, _modemSemaphore):
		""" Constructor de la clase 'Modem'. Utiliza la API 'pySerial' de
			Python para establecer un medio de comunicacion entre el usuario
			y el puerto donde se encuentra conectado el modem. Establece un
			'baudrate' y un 'timeout', donde este ultimo indica el intervalo
			de tiempo en segundos con el cual se hacen lecturas sobre el
			dispositivo. """
		self.modemSemaphore = _modemSemaphore
		self.modemInstance = serial.Serial()
		self.modemInstance.baudrate = 115200
		self.modemInstance.timeout = 5

	def __del__(self):
		""" Destructor de la clase 'Modem'. Cierra la conexion establecida
			con el modem. """
		self.modemInstance.close()
		logger.write('INFO', '[SMS] Objeto destruido.')

	def sendAT(self, atCommand):
		""" Se encarga de enviarle un comando AT el modem. Espera la respuesta
			a ese comando, antes de continuar.
			@param atCommand: comando AT que se quiere ejecutar
			@type atCommand: str
			@return: respuesta del modem, al comando AT ingresado
			@rtype: list """
		try:
			self.modemSemaphore.acquire()
			self.atError = False
			self.modemInstance.write(atCommand)				  # Envio el comando AT al modem
			self.modemOutput = self.modemInstance.readlines() # Espero la respuesta
		except serial.serialutil.SerialException:
			self.atError = True
			logger.write('ERROR', '[SMS] Error al intentar escribir %s sobre el dispositivo módem.' % atCommand)
		finally:
			# Verificamos si se produjo algún tipo de error relacionado con el comando AT
			atCommand = atCommand.replace('\r','')
			if self.modemOutput is not None:
				for i, outputElement in enumerate(self.modemOutput):
					if outputElement.startswith('+CME ERROR'):
						self.atError = True
						errorCode = int(outputElement.replace('+CME ERROR: ', ''))
						print atCommand + ' - ' + errorList.CME_ERRORS[errorCode] + '.'
					elif outputElement.startswith('+CMS ERROR'):
						self.atError = True
						errorCode = int(outputElement.replace('+CMS ERROR: ', ''))
						print atCommand + ' - ' + errorList.CMS_ERRORS[errorCode] + '.'
					elif outputElement.startswith('NO CARRIER'):
						self.atError = True
						print atCommand + ' - ' + errorList.NO_CARRIER + '.'
					elif outputElement.startswith('ERROR'):
						self.atError = True
						print atCommand + ' - ' + errorList.NO_CARRIER + '.'
			self.modemSemaphore.release()
			return self.modemOutput

class Sms(Modem):
	""" Subclase de 'Modem' correspondiente al modo de operacion con el que se va
		a trabajar. """
	smsAmount = 0
	smsIndex = 0
	smsHeader = ''
	smsBody = ''
	smsMessage = ''
	telephoneNumber = 1234567890

	receptionList = list()
	smsHeaderList = list()
	smsBodyList = list()

	receptionBuffer = Queue.Queue()
	isActive = False

	def __init__(self, _receptionBuffer, _modemSemaphore):
		""" Constructor de la clase 'Sms'. Configura el modem para operar en modo mensajes
			de texto, indica el sitio donde se van a almacenar los mensajes recibidos,
			habilita notificacion para los SMS entrantes y establece el numero del centro
			de mensajes CLARO para poder enviar mensajes de texto (este campo puede variar
			dependiendo de la compania de telefonia de la tarjeta SIM). """
		Modem.__init__(self, _modemSemaphore)
		self.receptionBuffer = _receptionBuffer

	def connect(self, _serialPort):
		self.modemInstance.port = _serialPort
		self.modemInstance.open()
		self.modemInstance.flushInput()
		self.modemInstance.flushOutput()
		time.sleep(1.5)
		self.sendAT('ATE1\r')					# Habilitamos el echo
		self.sendAT('AT+CMGF=1\r')				# Modo para Sms
		self.sendAT('AT+CPMS="ME","ME","ME"\r') # Lugar de almacenamiento de los mensajes (memoria del dispositivo)
		self.sendAT('AT+CNMI=1,1,0,0,0\r')		# Habilito notificacion de mensaje entrante
		self.sendAT('AT+CSCA="+' + str(JSON_CONFIG["SMS"]["CLARO_MESSAGES_CENTER"]) + '"\r') # Centro de mensajes CLARO

	def receive(self):
		""" Funcion que se encarga consultar al modem por algun mensaje SMS entrante. Envia al
			mismo el comando AT que devuelve los mensajes de texto no leidos (que por ende seran
			los nuevos) y que en caso de obtenerlos, los envia de a uno al modulo de procesamiento
			para su examen. Si el remitente del mensaje se encuentra registrado (en el archivo
			'contactList') se procede a procesar el cuerpo del SMS, o en caso contrario, se envia
			una notificacion informandole que no es posible realizar la operacion solicitada.
			Tambien cada un cierto tiempo dado por el intervalo de temporizacion, envia a un numero
			de telefono dado por 'DESTINATION_NUMBER' un mensaje de actualizacion, que por el momento
			estara compuesto de un 'TimeStamp'. """
		while self.isActive:
			# Mientras no se haya recibido ningun mensaje de texto y el temporizador no haya expirado...
			while self.smsAmount == 0 and self.isActive:
				# ... sigo esperando hasta que llegue algun mensaje de texto o vensa el timer.
				time.sleep(3)
				self.receptionList = self.sendAT('AT+CMGL="REC UNREAD"\r')
				# Ejemplo de receptionList[0]: AT+CMGL="REC UNREAD"\r\r\n
				# Ejemplo de receptionList[1]: +CMGL: 0,"REC UNREAD","+5493512560536",,"14/10/26,17:12:04-12"\r\n
				# Ejemplo de receptionList[2]: primero\r\n
				# Ejemplo de receptionList[3]: +CMGL: 1,"REC UNREAD","+5493512560536",,"14/10/26,17:15:10-12"\r\n
				# Ejemplo de receptionList[4]: segundo\r\n
				# Ejemplo de receptionList[5]: \r\n
				# Ejemplo de receptionList[6]: OK\r\n
				if self.receptionList is not None:
					for receptionIndex, receptionElement in enumerate(self.receptionList):
						if receptionElement.startswith('+CMGL'):
							self.smsHeader = self.receptionList[receptionIndex]
							self.smsHeaderList.append(self.smsHeader)
							self.smsBody = self.receptionList[receptionIndex + 1]
							self.smsBodyList.append(self.smsBody)
							self.smsAmount += 1
						elif receptionElement.startswith('OK'):
							break
					# Ejemplo de smsHeaderList[0]: +CMGL: 0,"REC UNREAD","+5493512560536",,"14/10/26,17:12:04-12"\r\n
					# Ejemplo de smsBodyList[0]  : primero\r\n
					# Ejemplo de smsHeaderList[1]: +CMGL: 1,"REC UNREAD","+5493512560536",,"14/10/26,17:15:10-12"\r\n
					# Ejemplo de smsBodyList[1]  : segundo\r\n
			# Leemos los mensajes de texto recibidos...
			if self.isActive:
				logger.write('DEBUG', '[SMS] Ha(n) llegado ' + str(self.smsAmount) + ' nuevo(s) mensaje(s) de texto!')
				for self.smsHeader, self.smsBody in zip(self.smsHeaderList, self.smsBodyList):
					# Ejemplo smsHeader: +CMGL: 0,"REC UNREAD","+5493512560536",,"14/10/26,17:12:04-12"\r\n
					# Ejemplo smsBody  : primero\r\n
					self.telephoneNumber = self.getTelephoneNumber(self.smsHeader) # Obtenemos el numero de telefono
					logger.write('DEBUG','Procesando mensaje de ' + str(self.telephoneNumber))
					# Comprobamos si el remitente del mensaje (un teléfono) esta registrado...
					if self.telephoneNumber in contactList.allowedNumbers.values():
						self.smsMessage = self.getSmsBody(self.smsBody) # Obtenemos el mensaje de texto
						self.sendOutput(self.telephoneNumber, self.smsMessage) # -----> SOLO PARA LA DEMO <-----
						print 'Mensaje procesado correctamente.'
					else:
						# ... caso contrario, verificamos si el mensaje proviene de la pagina web de CLARO...
						if self.telephoneNumber == JSON_CONFIG["SMS"]["CLARO_WEB_PAGE"]:
							logger.write('DEBUG','[SMS] No es posible procesar mensajes enviados desde la pagina web!')
						# ... sino, comunicamos al usuario que no se encuentra registrado.
						else:
							logger.write('WARNING','[SMS] Imposible procesar una solicitud. El número no se encuentra registrado!')
							self.smsMessage = 'Imposible procesar la solicitud. Usted no se encuentra registrado!'
							#self.send(self.telephoneNumber, self.smsMessage)
					self.smsIndex = self.getSmsIndex(self.smsHeader.split(',')[0]) # Obtenemos el índice del mensaje en memoria
					self.removeSms(self.smsIndex) # Eliminamos el mensaje porque ya fue leído
					self.smsAmount -= 1 # Decrementamos la cantidad de mensajes a procesar
				self.smsHeaderList = []
				self.smsBodyList = []
			# ... sino, dejamos de leer los SMS
			else:
				break
		logger.write('WARNING', '[SMS] Funcion \'%s\' terminada.' % inspect.stack()[0][3])

	def send(self, telephoneNumber, smsMessage):
		""" Envia el comando AT correspondiente para enviar un mensaje de texto.
			@param telephoneNumber: numero de telefono del destinatario
			@type telephoneNumber: int
			@param smsMessage: mensaje de texto a enviar
			@type smsMessage: str """
		atResult01 = self.sendAT('AT+CMGS="' + str(telephoneNumber) + '"\r') # Numero al cual enviar el Sms
		atResult02 = self.sendAT(smsMessage + ascii.ctrl('z')) 				 # Mensaje de texto terminado en Ctrl+Z
		# --------------------- Caso de envío EXITOSO ---------------------
		# Ejemplo de atResult02[0]: Mensaje enviado desde el Modem.\x1a\r\n
		# Ejemplo de atResult02[1]: +CMGS: 17\r\n
		# Ejemplo de atResult02[3]: OK\r\n
		if self.atError:
			print 'Ocurrió un problema al enviar el mensaje.'
			return False
		else:
			for i, resultElement in enumerate(atResult02):
				if resultElement.startswith('+CMGS'):
					#self.smsIndex = self.getSmsIndex(atResult02[i].replace('\r\n', ''))
					#self.removeSms(self.smsIndex)
					self.removeAllSms()
					break
			print 'El mensaje fue enviado con éxito.'
			return True

	def removeSms(self, smsIndex):
		""" Envia el comando AT correspondiente para elimiar todos los mensajes del dispositivo.
			El comando AT tiene una serie de parametros, que dependiendo de cada uno de ellos
			indicara cual de los mensajes se quiere eliminar. En nuestro caso le indicaremos
			que elimine los mensajes leidos y los mensajes enviados, ya que fueron procesados
			y no los requerimos mas (ademas necesitamos ahorrar memoria, debido a que la misma
			es muy limitada). """
		self.sendAT('AT+CMGD=' + str(smsIndex) + '\r') # Elimina el mensaje especificado

	def removeAllSms(self):
		self.sendAT('AT+CMGD=1,2\r') # Elimina todos los mensajes leidos y enviados

	def getSmsIndex(self, atOutput):
		# Ejemplo de atOutput (para un mensaje recibido): +CMGL: 2
		# Ejemplo de atOutput (para un mensaje enviado) : +CMGS: 17
		# Quitamos el comando AT, dejando solamente el índice del mensaje en memoria
		if atOutput.startswith('+CMGL'):
			atOutput = atOutput.replace('+CMGL: ', '')
		elif atOutput.startswith('+CMGS'):
			atOutput = atOutput.replace('+CMGS: ', '')
		smsIndex = int(atOutput)
		return smsIndex

	def getTelephoneNumber(self, smsHeader):
		""" Procesa la cabecera del SMS.
			@return: numero de telefono del remitente
			@rtype: int """
		# Ejemplo de smsHeader recibido de un movil: +CMGL: 0,"REC UNREAD","+5493512560536",,"14/10/26,17:12:04-12"\r\n
		# Ejemplo de smsHeader recibido de la web  : +CMGL: 2,"REC UNREAD","876966",,"14/10/26,19:36:42-12"\r\n'
		smsHeader = smsHeader.replace('\r\n', '') # Quitamos el '\r\n' del final
		headerList = smsHeader.split(',')		  # Separamos la smsHeader por comas
		# Ejemplo de headerList[2]: "+5493512560536" | "876966"
		# Ejemplo de headerList[4]: "14/10/26 | "14/10/26
		# Ejemplo de headerList[5]: 17:12:04-12" | 19:36:42-12"
		headerList[2] = headerList[2].replace('"', '') # Quitamos las comillas
		# Ejemplo de headerList[2]: +5493512560536 | 876966
		# Nos fijamos si el origen del Sms es un telefono (podria haber venido desde la pagina web de CLARO)...
		if headerList[2].startswith('+549'):
			headerList[2] = headerList[2].replace('+549', '') # Quitamos el codigo de pais
			# Ejemplo de headerList[2]: 3512560536
		telephoneNumber = int(headerList[2])
		return telephoneNumber

	def getSmsBody(self, smsBody):
		""" Procesa el cuerpo del SMS.
			@return: salida del procesamiento (de acuerdo al contenido del cuerpo del mensaje)
			@rtype: list """
		# Ejemplo de smsBody: ls -l -a\r\n
		smsBody = smsBody.lower().replace('\r\n', '') # Ponemos todo en minusculas y quitamos el '\r\n' del final
		# Ejemplo de smsBody: ls -l -a
		return smsBody

	def sendCall(self, telephoneNumber):
		self.sendAT('ATD' + str(telephoneNumber) + '\r') # Numero al cual efectuar la llamada

	def sendOutput(self, telephoneNumber, smsMessage):
		try:
			subprocess.Popen(['gnome-terminal', '-x', 'sh', '-c', smsMessage + '; exec bash'], stderr = subprocess.PIPE)
			#subprocess.check_output(shlex.split(smsMessage), stderr = subprocess.PIPE)
			smsMessage = 'El comando se ejecuto exitosamente!'
		except subprocess.CalledProcessError as e: # El comando es correcto pero le faltan parámetros
			smsMessage = 'El comando es correcto pero le faltan parámetros!'
		except OSError as e: # El comando no fue encontrado (el ejecutable no existe)
			smsMessage = 'El comando es incorrecto! No se encontró el ejecutable.'
		finally:
			#self.send(telephoneNumber, smsMessage)
			pass
