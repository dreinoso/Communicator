# coding=utf-8

import os
import pickle
import bluetooth

import logger
import messageClass

# Tamano del buffer en bytes (cantidad de caracteres)
BUFFER_SIZE = 1024

class BluetoothTransmitter():

	def __init__(self):
		"""Creación de la clase de transmisión de paquetes Bluetooth."""

	def send(self, message, remoteSocket):
		'''Dependiendo del tipo de mensaje de que se trate, el envio del mensaje
		se comportara diferente'''
		# Comprobación de envío de texto plano
		if isinstance(message, messageClass.SimpleMessage) and not message.isInstance:
			return self.sendMessage(message.plainText, remoteSocket)
		# Comprobación de envío de archivo
		elif isinstance(message, messageClass.FileMessage) and not message.isInstance:
			return self.sendFile(message.fileName, remoteSocket)
		# Comprobación de envío de instancia de mensaje
		else:
			return self.sendMessageInstance(message, remoteSocket)

	def sendMessage(self, plainText, remoteSocket):
		'''Envío de mensaje simple'''
		try:
			remoteSocket.send(plainText)
			logger.write('INFO', '[BLUETOOTH] Mensaje enviado correctamente!')
			return True
		except Exception as errorMessage:
			logger.write('WARNING', '[BLUETOOTH] Mensaje no enviado: %s' % str(errorMessage))
			return False
		finally:
			# Cierra la conexion del socket cliente
			remoteSocket.close()

	def sendFile(self, fileName, remoteSocket):
		'''Envio de archivo simple, es decir unicamente el archivo sin una instancia de control.
		Esta función solo se llama en caso de que el archivo exista. Por lo que solo resta abrirlo.
		Se hacen sucecivas lecturas del archivo, y se envian. El receptor se encarga de recibir y 
		rearmar	el archivo. Se utiliza una sincronización de mensajes para evitar perder paquetes,
		además que lleguen en orden.'''
		try:
			absoluteFilePath = os.path.abspath(fileName)
			fileDirectory, fileName = os.path.split(absoluteFilePath)
			fileObject = open(absoluteFilePath, 'rb')
			remoteSocket.send('START_OF_FILE')
			remoteSocket.recv(BUFFER_SIZE) # ACK
			remoteSocket.send(fileName) # Enviamos el nombre del archivo
			# Recibe confirmación para comenzar a transmitir (READY)
			if remoteSocket.recv(BUFFER_SIZE) == "READY":
				# Guardamos la posición inicial del archivo (donde comienza)
				fileBeginning = fileObject.tell()
				# Apuntamos al final del archivo
				fileObject.seek(0, os.SEEK_END)
				# Obtenemos la posición final del mismo (que sería el tamaño)
				fileSize = fileObject.tell()
				# Apuntamos nuevamente al comienzo del archivo, para comenzar a transmitir
				fileObject.seek(fileBeginning, os.SEEK_SET)
				# Envio del contenido del archivo
				bytesSent = 0
				logger.write('DEBUG', '[BLUETOOTH] Transfiriendo archivo \'%s\'...' % fileName)
				while bytesSent < fileSize:
					outputData = fileObject.read(BUFFER_SIZE)
					remoteSocket.send(outputData)
					bytesSent += len(outputData)
					remoteSocket.recv(BUFFER_SIZE) # ACK
				fileObject.close()
				remoteSocket.send('EOF')
				remoteSocket.recv(BUFFER_SIZE) # IMPORTANTE ACK, no borrar.
				logger.write('INFO', '[BLUETOOTH] Archivo \'%s\' enviado correctamente!' % fileName)
				return True
			# Recibe 'FILE_EXISTS'
			else:
				logger.write('WARNING', '[BLUETOOTH] El archivo \'%s\' ya existe, fue rechazado!' % fileName)
				return True # Para que no se vuelva a intentar el envio. El control esta en la notificación		
		except Exception as errorMessage:
			logger.write('WARNING', '[BLUETOOTH] Archivo \'%s\' no enviado: %s' % (fileName, str(errorMessage)))
			return False
		finally:
			remoteSocket.close() # Cierra la conexion del socket cliente

	def sendMessageInstance(self, message, remoteSocket):
		'''Envió de la instancia mensaje. Primero debe realizarse una serialización de la clase
		y enviar de a BUFFER_SIZE cantidad de caracteres, en definitiva se trata de una cadena.'''
		try:
			remoteSocket.send('START_OF_INSTANCE') # Indicamos al otro extremo que vamos a transmitir una instancia de mensaje
			remoteSocket.recv(BUFFER_SIZE) # Espera de confirmación ACK
			messageSerialized = pickle.dumps(message) # Serialización de la instancia
			bytesSent = 0 
			while bytesSent < len(messageSerialized): # Comienza el envio de la instancia
				outputData = messageSerialized[bytesSent:bytesSent + BUFFER_SIZE]
				remoteSocket.send(outputData)
				bytesSent = bytesSent + BUFFER_SIZE
				remoteSocket.recv(BUFFER_SIZE) # ACK
			remoteSocket.send('END_OF_INSTANCE')
			################################################################################
			if isinstance(message, messageClass.FileMessage):
				self.sendFile(message.fileName, remoteSocket)
				return True
			else:
				logger.write('INFO', '[BLUETOOTH] Instancia de mensaje enviado correctamente!')
				return True
			################################################################################
		except Exception as errorMessage:
			logger.write('WARNING', '[BLUETOOTH] Instancia de mensaje no enviado: %s' % str(errorMessage))
			return False
		finally:
			# Cierra la conexion del socket cliente
			remoteSocket.close()