import os
import glob
import string
import argparse
from os import listdir
from pickle import dump
from pickle import load
from PIL import Image
from numpy import array
from numpy import argmax
from nltk.translate.bleu_score import corpus_bleu
from keras.utils import to_categorical
from keras.applications.vgg16 import VGG16
from keras.preprocessing.image import load_img
from keras.preprocessing.image import img_to_array
from keras.preprocessing.text import Tokenizer
from keras.preprocessing.sequence import pad_sequences
from keras.applications.vgg16 import preprocess_input
from keras.utils import plot_model
from keras.models import Model
from keras.models import load_model
from keras.layers import Input
from keras.layers import Dense
from keras.layers import LSTM
from keras.layers import Embedding
from keras.layers import Dropout
from keras.layers.merge import add
from keras.callbacks import ModelCheckpoint

directory = "D:/Study/Dataset/Flickr8k_Dataset/Flicker8k_Dataset/"

def extract_features(source):
	# load the model
	model = VGG16()
	# re-structure the model
	model.layers.pop()
	model = Model(inputs=model.inputs, outputs=model.layers[-1].output)
	# extract features from each photo
	if os.path.isdir(source):
		features = dict()
		for name in listdir(directory):
			# load an image from file
			filename = directory + '/' + name
			feature = extract_feature(filename, model)
			# get image id
			image_id = name.split('.')[0]
			# store feature
			features[image_id] = feature
			print('>%s' % name)
		return features
	elif os.path.isfile(source):
		return extract_feature(source, model)
	else:
		raise Exception("Source for images needs to be a file or directory.")


# extract a feature for a single photo
def extract_feature(filename, model):
	# load the photo
	image = load_img(filename, target_size=(224, 224))
	# convert the image pixels to a numpy array
	image = img_to_array(image)
	# reshape data for the model
	image = image.reshape((1, image.shape[0], image.shape[1], image.shape[2]))
	# prepare the image for the VGG model
	image = preprocess_input(image)
	# get features
	feature = model.predict(image, verbose=0)
	return feature

# load doc into memory
def load_doc(filename):
	# open the file as read only
	file = open(filename, 'r')
	# read all text
	text = file.read()
	# close the file
	file.close()
	return text

# extract descriptions for images
def load_descriptions(doc):
	mapping = dict()
	# process lines
	for line in doc.split('\n'):
		# split line by white space
		tokens = line.split()
		if len(line) < 2:
			continue
		# take the first token as the image id, the rest as the description
		image_id, image_desc = tokens[0], tokens[1:]
		# remove filename from image id
		image_id = image_id.split('.')[0]
		# convert description tokens back to string
		image_desc = ' '.join(image_desc)
		# create the list if needed
		if image_id not in mapping:
			mapping[image_id] = list()
		# store description
		mapping[image_id].append(image_desc)
	return mapping

def clean_descriptions(descriptions):
	# prepare translation table for removing punctuation
	table = str.maketrans('', '', string.punctuation)
	for key, desc_list in descriptions.items():
		for i in range(len(desc_list)):
			desc = desc_list[i]
			# tokenize
			desc = desc.split()
			# convert to lower case
			desc = [word.lower() for word in desc]
			# remove punctuation from each token
			desc = [w.translate(table) for w in desc]
			# remove hanging 's' and 'a'
			desc = [word for word in desc if len(word)>1]
			# remove tokens with numbers in them
			desc = [word for word in desc if word.isalpha()]
			# store as string
			desc_list[i] =  ' '.join(desc)

# convert the loaded descriptions into a vocabulary of words
def to_vocabulary(descriptions):
	# build a list of all description strings
	vocab = set()
	for key in descriptions.keys():
		[vocab.update(d.split()) for d in descriptions[key]]
	return vocab

# save descriptions to file, one per line
def save_descriptions(descriptions, filename):
	lines = list()
	for key, desc_list in descriptions.items():
		for desc in desc_list:
			lines.append(key + ' ' + desc)
	data = '\n'.join(lines)
	file = open(filename, 'w')
	file.write(data)
	file.close()

# load a pre-defined list of photo identifiers
def load_set(filename):
	doc = load_doc(filename)
	dataset = list()
	# process line by line
	for line in doc.split('\n'):
		# skip empty lines
		if len(line) < 1:
			continue
		# get the image identifier
		identifier = line.split('.')[0]
		dataset.append(identifier)
	return set(dataset)

# load clean descriptions into memory
def load_clean_descriptions(filename, dataset):
	# load document
	doc = load_doc(filename)
	descriptions = dict()
	for line in doc.split('\n'):
		# split line by white space
		tokens = line.split()
		# split id from description
		image_id, image_desc = tokens[0], tokens[1:]
		# skip images not in the set
		if image_id in dataset:
			# create list
			if image_id not in descriptions:
				descriptions[image_id] = list()
			# wrap description in tokens
			desc = 'startseq ' + ' '.join(image_desc) + ' endseq'
			# store
			descriptions[image_id].append(desc)
	return descriptions

# load photo features
def load_photo_features(filename, dataset):
	# load all features
	all_features = load(open(filename, 'rb'))
	# filter features
	features = {k: all_features[k] for k in dataset}
	return features

# convert a dictionary of clean descriptions to a list of descriptions
def to_lines(descriptions):
	all_desc = list()
	for key in descriptions.keys():
		[all_desc.append(d) for d in descriptions[key]]
	return all_desc

# fit a tokenizer given caption descriptions
# every string extracted from the list of descriptions is encoded individually
def create_tokenizer(descriptions):
	lines = to_lines(descriptions)
	tokenizer = Tokenizer()
	tokenizer.fit_on_texts(lines)
	return tokenizer

def create_sequences(tokenizer, max_length, desc_list, photo):
	X1, X2, y = list(), list(), list()
	# walk through each description for the image
	for desc in desc_list:
		# encode the sequence
		seq = tokenizer.texts_to_sequences([desc])[0]
		# split one sequence into multiple X,y pairs
		for i in range(1, len(seq)):
			# split into input and output pair
			in_seq, out_seq = seq[:i], seq[i]
			# pad input sequence
			in_seq = pad_sequences([in_seq], maxlen=max_length)[0]
			# encode output sequence
			out_seq = to_categorical([out_seq], num_classes=vocab_size)[0]
			# store
			X1.append(photo)
			X2.append(in_seq)
			y.append(out_seq)
	return array(X1), array(X2), array(y)


# data generator, intended to be used in a call to model.fit_generator()
def data_generator(descriptions, photos, tokenizer, max_length):
	# loop for ever over images
	while 1:
		for key, desc_list in descriptions.items():
			# retrieve the photo feature
			photo = photos[key][0]
			in_img, in_seq, out_word = create_sequences(tokenizer, max_length, desc_list, photo)
			yield [[in_img, in_seq], out_word]


# calculate the length of the description with the most words
def get_max_length(descriptions):
	lines = to_lines(descriptions)
	return max(len(d.split()) for d in lines)

#define the captioning model
def define_model(vocab_size, max_length):
	inputs1 = Input(shape=(4096,))
	fe1 = Dropout(0.5)(inputs1)
	fe2 = Dense(256, activation='relu')(fe1)
    # sequence model
	inputs2 = Input(shape=(max_length,))
	se1 = Embedding(vocab_size, 256, mask_zero=True)(inputs2)
	se2 = Dropout(0.5)(se1)
	se3 = LSTM(256)(se2)
    # decoder model
	decoder1 = add([fe2, se3])
	decoder2 = Dense(256, activation='relu')(decoder1)
	outputs = Dense(vocab_size, activation='softmax')(decoder2)
	model = Model(inputs=[inputs1, inputs2], outputs=outputs)
    # compile model
	model.compile(loss='categorical_crossentropy', optimizer='adam')
    # summarize model
	model.summary()
	plot_model(model, to_file='model.png', show_shapes=True)
	return model

#map an integet to a word
def word_for_id(integer, tokenizer):
	for word, index in tokenizer.word_index.items():
		if index == integer:
			return word
	return None

# generate a description for an image
def generate_desc(model, tokenizer, photo, max_length):
	# seed the generation process
	in_text = 'startseq'
	# iterate over the whole length of the sequence
	for i in range(max_length):
		# integer encode input sequence
		sequence = tokenizer.texts_to_sequences([in_text])[0]
		# pad input
		sequence = pad_sequences([sequence], maxlen=max_length)
		# predict next word
		yhat = model.predict([photo,sequence], verbose=0)
		# convert probability to integer
		yhat = argmax(yhat)
		# map integer to word
		word = word_for_id(yhat, tokenizer)
		# stop if we cannot map the word
		if word is None:
			break
		# append as input for generating the next word
		in_text += ' ' + word
		# stop if we predict the end of the sequence
		if word == 'endseq':
			break
	return in_text

# evaluate the skill of the model
def evaluate_model(model, descriptions, photos, tokenizer, max_length):
	actual, predicted = list(), list()
	# step over the whole set
	for key, desc_list in descriptions.items():
		# generate description
		yhat = generate_desc(model, tokenizer, photos[key], max_length)
		# store actual and predicted
		references = [d.split() for d in desc_list]
		actual.append(references)
		predicted.append(yhat.split())
	# calculate BLEU score
	print('BLEU-1: %f' % corpus_bleu(actual, predicted, weights=(1.0, 0, 0, 0)))
	print('BLEU-2: %f' % corpus_bleu(actual, predicted, weights=(0.5, 0.5, 0, 0)))
	print('BLEU-3: %f' % corpus_bleu(actual, predicted, weights=(0.3, 0.3, 0.3, 0)))
	print('BLEU-4: %f' % corpus_bleu(actual, predicted, weights=(0.25, 0.25, 0.25, 0.25)))


def prepare_image_data():
	# Prepare the Image Data
	# extract features from all images
	directory = 'D:/Study/Dataset/Flickr8k_Dataset/Flicker8k_Dataset'
	if os.path.exists('features.pkl'):
		print('Features already extracted into \'features.plk\' file.')
	else:
		features = extract_features(directory)
		print('Extracted Features: %d' % len(features))
		# save to file
		dump(features, open('features.pkl', 'wb'))


def prepare_text_data():
	# Prepare the Text Data
	# load file containing all text descriptions of the images
	filename = 'D:/Study/Dataset/Flickr8k_text/Flickr8k.token.txt'
	# load descriptions
	doc = load_doc(filename)
	# parse descriptions
	descriptions = load_descriptions(doc)
	print('Loaded Descriptions: %d ' % len(descriptions))
	# clean descriptions
	clean_descriptions(descriptions)

	# summarize vocabulary
	vocabulary = to_vocabulary(descriptions)
	print('Vocabulary Size: %d' % len(vocabulary))

	# save descriptions
	save_descriptions(descriptions, 'descriptions.txt')


def prepare_training_data():
	# load training dataset (6K)
	filename = 'D:/Study/Dataset/Flickr8k_text/Flickr_8k.trainImages.txt'
	training_images_data = load_set(filename)
	print('Training Images Dataset: %d' % len(training_images_data))
	# descriptions
	training_data_descriptions = load_clean_descriptions('descriptions.txt', training_images_data)
	print('Descriptions for Training Images Dataset: %d' % len(training_data_descriptions))
	# photo features
	train_features = load_photo_features('features.pkl', training_images_data)
	print('Extracted Training Image Features: %d' % len(train_features))
	return train_features, training_data_descriptions


def prepare_tokenizer(training_data_descriptions):
	if os.path.exists('tokenizer.pkl'):
		print('Tokenizer already created and saved into \'tokenizer.pkl\'')
		print('Loading tokenizer ...')
		tokenizer = load(open('tokenizer.pkl', 'rb'))
	else:
		# prepare tokenizer
		tokenizer = create_tokenizer(training_data_descriptions)
		# save the tokenizer
		dump(tokenizer, open('tokenizer.pkl', 'wb'))
	return tokenizer


def summarize_vocab(tokenizer):
	vocab_size = len(tokenizer.word_index) + 1
	print('Vocabulary Size: %d' % vocab_size)
	return vocab_size

def max_length_desc(training_data_descriptions):
	# determine the maximum sequence length
	max_length = get_max_length(training_data_descriptions)
	print('Maximum Description Length (in words): %d' % max_length)
	return max_length

def load_pretrained_model(filename):
	print('Loading latest model ...')
	return load_model(filename)


def load_test_data():
	# load test set
	filename = 'D:/Study/Dataset/Flickr8k_text/Flickr_8k.devImages.txt'
	test_images_data = load_set(filename)
	print('Test Images Dataset: %d' % len(test_images_data))
	# descriptions
	test_data_descriptions = load_clean_descriptions('descriptions.txt', test_images_data)
	print('Descriptions for Test Images Dataset: %d' % len(test_data_descriptions))
	# photo features
	test_features = load_photo_features('features.pkl', test_data_descriptions)
	print('Extracted Test Image Features: %d' % len(test_features))
	return test_features, test_data_descriptions


def clean_old_model_checkpoints():
	models = glob.glob('*.h5')
	for model in models:
		try:
			os.remove(model)
		except:
			print('Failed to remove %d' % model)


def train(vocab_size, training_data_descriptions, train_features, tokenizer, max_length):
	clean_old_model_checkpoints()
	# define the model
	model = define_model(vocab_size, max_length)


def evaluate(model, test_data_descriptions, test_features, tokenizer, max_length):
	evaluate_model(model, test_data_descriptions, test_features, tokenizer, max_length)


def test(model, tokenizer, max_length):
	# pre-define the max sequence length (from training)
	max_length = 34
	# load and prepare the photograph
	photo = extract_features('D:/Study/Dataset/Flickr8k_Dataset/Flicker8k_Dataset/1009434119_febe49276a.jpg')
	# generate description
	description = generate_desc(model, tokenizer, photo, max_length)
	print(description)


if __name__ == '__main__':
	parser = argparse.ArgumentParser()
	parser.add_argument('--op', default='evaluate')

	# All the preparation
	prepare_image_data()
	prepare_text_data()
	training_features, training_desc = prepare_training_data()
	test_data_features, test_data_descriptions = load_test_data()
	tokenizer = prepare_tokenizer(training_desc)
	vocab_size = summarize_vocab(tokenizer)
	max_length = max_length_desc(training_desc)
	pretrained_model = load_pretrained_model('D:/Study/Caption-Generator/model_18.h5')


	args = parser.parse_args()

	if args.op == 'train':
		print('ALL SET FOR TRAINING ...')
		train(vocab_size, training_desc, training_features, tokenizer, max_length)
	elif args.op == 'evaluate':
		print('ALL SET FOR EVALUATING ...')
		evaluate(pretrained_model, test_data_descriptions, test_data_features, tokenizer, max_length)
	elif args.op == 'test':
		print('ALL SET FOR TESTING ...')
		test(pretrained_model, tokenizer, max_length)
	else:
		raise Exception('Choose valid operation: \'train\', \'evaluate\' or \'test\'')
