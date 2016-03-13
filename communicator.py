 # coding=utf-8

"""Modulo principal que se encarga del control de los demás objetos y submódulos
	para permitir la comunicación. 
	@author: Gonzalez Leonardo Mauricio
	@author: Reinoso Ever Denis
	@organization: UNC - Fcefyn
	@date: Lunes 16 de Mayo de 2015 """

import os
import sys
import time
import json
import Queue

currentDirectory = os.getcwd() 
if not currentDirectory.endswith('Communicator'):
	os.chdir(currentDirectory + '/Communicator')

sys.path.append(os.path.abspath('Email/'))
sys.path.append(os.path.abspath('Modem/'))
sys.path.append(os.path.abspath('Network/'))
sys.path.append(os.path.abspath('Bluetooth/'))

import emailClass
import modemClass
import networkClass
import bluetoothClass

import logger
import contactList
import messageClass
import controllerClass
import transmitterClass

JSON_FILE = 'config.json'
JSON_CONFIG = json.load(open(JSON_FILE))

os.chdir(currentDirectory)

logger.set() # Solo se setea una vez, todos los objetos usan esta misma configuración

smsInstance = modemClass.Sms
gprsInstance = modemClass.Gprs
emailInstance = emailClass.Email
networkInstance = networkClass.Network
bluetoothInstance = bluetoothClass.Bluetooth

controllerInstance = controllerClass.Controller    # Instancia que pone enfuncionamiento los periféricos
transmitterInstance = transmitterClass.Transmitter # Instancia para la transmisión de paquetes

def open():
	"""Se realiza la apertura, inicialización de los componentes que se tengan disponibles
	"""
	global receptionBuffer, transmissionBuffer 
	global controllerInstance, transmitterInstance
	global smsInstance, gprsInstance, emailInstance, networkInstance, bluetoothInstance

	# Creamos los buffers de recepción y transmisión, respectivamente
	receptionBuffer = Queue.PriorityQueue(JSON_CONFIG["COMMUNICATOR"]["RECEPTION_BUFFER"])
	transmissionBuffer = Queue.PriorityQueue(JSON_CONFIG["COMMUNICATOR"]["TRANSMISSION_BUFFER"])

	# Creamos las instancias de los periféricos
	gprsInstance = modemClass.Gprs()
	smsInstance = modemClass.Sms(receptionBuffer)
	emailInstance = emailClass.Email(receptionBuffer)
	networkInstance = networkClass.Network(receptionBuffer)
	bluetoothInstance = bluetoothClass.Bluetooth(receptionBuffer)

	# Creamos la instancia para levantar las conexiones
	controllerInstance = controllerClass.Controller(smsInstance, gprsInstance, emailInstance, networkInstance, bluetoothInstance)

	# Creamos la instancia para la transmisión de paquetes
	transmitterInstance = transmitterClass.Transmitter(smsInstance, emailInstance, networkInstance, bluetoothInstance, transmissionBuffer)

	# Ponemos en marcha el controlador de medios de comunicación y la transmisión de mensajes
	controllerInstance.start()
	transmitterInstance.start()

	return True

def close():
	"""Se cierran los componentes del sistema, unicamente los abiertos previamente"""
	global receptionBuffer, transmissionBuffer
	global controllerInstance, transmitterInstance
	global smsInstance, gprsInstance, emailInstance, networkInstance, bluetoothInstance

	# Frenamos la transmisión de mensajes
	transmitterInstance.isActive = False
	transmitterInstance.join()

	# Frenamos la verificación de las conexiones
	controllerInstance.isActive = False
	controllerInstance.join()

	# Destruimos todas las instancias de comunicación
	del smsInstance
	del gprsInstance
	del emailInstance
	del networkInstance
	del bluetoothInstance

	# Destruimos los buffer de recepción y transmisión
	del receptionBuffer
	del transmissionBuffer

	# Destruimos las instancias de manejo del comunicador
	del controllerInstance
	del transmitterInstance

	return True

def send(message, receiver = None, device = None):
	"""Se almacena en el buffer de transmisión el paquete a ser enviado, se guardara
	en caso de que se hayan establecido parametros correctos. En caso de tratarse 
	de un mensaje simple o archivo simple, se los convierte en Instancias para simplificar
	el manejo del mensaje por el transmisor. Pero se envia unicamente la cadena de
	texto o el archivo
	@param message: paquete a ser enviado, ya sea mensaje (o instancia) o un archivo (o instancia)
	@param receiver: es el contacto al que se envia el mensaje
	@param device: modo de envío preferente para ese mensaje en particular (puede no definirse)"""
	global transmissionBuffer

	if not transmissionBuffer.full():
		# Si el mensaje no es una instancia, la creamos para poder hacer el manejo de transmisión con prioridad
		if not isinstance(message, messageClass.Message):
			# Al no tratarse de una instancia, no podemos conocer el destino salvo que el usuario lo especifique
			if receiver is not None:
				tmpMessage = message
				# Creamos la instancia general de un mensaje
				message = messageClass.Message('', receiver)
				# Verificamos si el mensaje es una ruta a un archivo (path relativo o path absoluto)...
				if os.path.isfile(tmpMessage):
					# Insertamos el campo 'fileName'
					setattr(message, 'fileName', tmpMessage)
				# Entonces es un mensaje de texto plano
				else:
					# Insertamos el campo 'plainText'
					setattr(message, 'plainText', tmpMessage)
				# Le asignamos una prioridad
				setattr(message, 'priority', 10)
			else:
				logger.write('ERROR', '[COMMUNICATOR] No se especificó un destino para el mensaje!')
				return False
		################################## VERIFICACIÓN DE CONTACTO ##################################
		# Antes de poner el mensaje en el buffer, comprobamos que el cliente esté en algún diccionario
		clientList = list() + contactList.allowedIpAddress.keys()
		clientList += contactList.allowedMacAddress.keys()
		clientList += contactList.allowedEmails.keys()
		clientList += contactList.allowedNumbers.keys()
		# Quitamos los clientes repetidos
		clientList = list(set(clientList))
		# Buscamos por lo menos una coincidencia, para luego intentar hacer el envío
		if message.receiver not in clientList:
			# El cliente fue encontrado como entrada de un diccionario
			logger.write('WARNING', '[COMMUNICATOR] \'%s\' no registrado! Mensaje descartado...' % message.receiver)
			return False
		################################ FIN VERIFICACIÓN DE CONTACTO ################################
		# Establecemos el tiempo que permanecerá el mensaje en el buffer antes de ser desechado en caso de no ser enviado
		setattr(message, 'timeOut', 20)
		# Damos mayor prioridad al dispositivo referenciado por 'device' (si es que hay alguno)
		setattr(message, 'device', device)
		# Indicamos con una marca de tiempo, la hora exacta en la que se almacenó el mensaje en el buffer de transmisión
		setattr(message, 'timeStamp', time.time())
		# Almacenamos el mensaje en el buffer de transmisión, con la prioridad correspondiente
		transmissionBuffer.put((100 - message.priority, message))
		logger.write('INFO', '[COMMUNICATOR] Mensaje almacenado en el buffer esperando ser enviado...')
		return True
	else:
		logger.write('WARNING', '[COMMUNICATOR] El buffer de transmisión esta lleno, imposible enviar!')
		return False

def receive():
	"""Se obtiene de un buffer circular el mensaje recibido mas antiguo.
	@return: Mensaje recibido
	@rtype: str"""
	if receptionBuffer.qsize() > 0:
		# El elemento 0 es la prioridad, por eso sacamos el 1 porque es el mensaje
		return receptionBuffer.get_nowait()[1]
	else:
		logger.write('INFO', '[COMMUNICATOR] El buffer de mensajes esta vacío!')
		return None

def lenght():
	"""Devuelve el tamaño del buffer de recepción.
	@return: Cantidad de elementos en el buffer
	@rtype: int"""
	if receptionBuffer.qsize() == None:
		return 0
	else:
		return receptionBuffer.qsize()

def connectGprs():
	# Si no hay una conexión GPRS activa, intentamos conectarnos a la red
	if not gprsInstance.isActive:
		return gprsInstance.connect()
	else:
		logger.write('WARNING', '[GRPS] Ya existe una conexión activa con la red!')
		return True

def disconnectGprs():
	return gprsInstance.disconnect()
