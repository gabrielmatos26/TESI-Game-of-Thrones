# Copyright 2015 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import collections
import math
import os
import random
import zipfile

import numpy as np
from six.moves import urllib
from six.moves import xrange  # pylint: disable=redefined-builtin
import tensorflow as tf

# Read the data into a list of strings.
def read_data(filename):
  """Extract the first file enclosed in a zip file as a list of words"""
  with zipfile.ZipFile(filename) as f:
    data = tf.compat.as_str(f.read(f.namelist()[0])).split()
  return data

#Build the dictionary and replace rare words with UNK token.
# vocabulary_size = 50000

def build_dataset(words, vocabulary_size):
  count = [['UNK', -1]]
  count.extend(collections.Counter(words).most_common(vocabulary_size - 1))
  dictionary = dict()
  for word, _ in count:
    dictionary[word] = len(dictionary)
  data = list()
  unk_count = 0
  for word in words:
    if word in dictionary:
      index = dictionary[word]
    else:
      index = 0  # dictionary['UNK']
      unk_count += 1
    data.append(index)
  count[0][1] = unk_count
  reverse_dictionary = dict(zip(dictionary.values(), dictionary.keys()))
  return data, count, dictionary, reverse_dictionary


data_index = 0
# Step 3: Function to generate a training batch for the skip-gram model.
def generate_batch(batch_size, num_skips, skip_window, data):
  global data_index
  assert batch_size % num_skips == 0
  assert num_skips <= 2 * skip_window
  batch = np.ndarray(shape=(batch_size), dtype=np.int32)
  labels = np.ndarray(shape=(batch_size, 1), dtype=np.int32)
  span = 2 * skip_window + 1 # [ skip_window target skip_window ]
  buffer = collections.deque(maxlen=span)
  for _ in range(span):
    buffer.append(data[data_index])
    data_index = (data_index + 1) % len(data)
  for i in range(batch_size // num_skips):
    target = skip_window  # target label at the center of the buffer
    targets_to_avoid = [ skip_window ]
    for j in range(num_skips):
      while target in targets_to_avoid:
        target = random.randint(0, span - 1)
      targets_to_avoid.append(target)
      batch[i * num_skips + j] = buffer[skip_window]
      labels[i * num_skips + j, 0] = buffer[target]
    buffer.append(data[data_index])
    data_index = (data_index + 1) % len(data)
  return batch, labels

import matplotlib.pyplot as plt
from sklearn.cluster import KMeans

def plot_with_labels(low_dim_embs, labels, filename='tsne.png', y_pred=None):
  assert low_dim_embs.shape[0] >= len(labels), "More labels than embeddings"
  plt.figure(figsize=(24, 24))  #in inches
  colors = ["blue","green","red","yellow","black","purple"]
  flag = 1
  if y_pred is None:
  	flag = 0
  for i, label in enumerate(labels):
    x, y = low_dim_embs[i,:]
    if flag == 0:
    	plt.scatter(x, y, color="green")
    else:
		plt.scatter(x, y, color=colors[y_pred[i]])

    plt.annotate(label,
                 xy=(x, y),
                 xytext=(5, 2),
                 textcoords='offset points',
                 ha='right',
                 va='bottom')

  plt.savefig(filename)

final_embeddings = []
def word2vec(filename, vocabulary_size, num_steps):
	global final_embeddings
	words = read_data(filename)
	print('Data size', len(words))
	data, count, dictionary, reverse_dictionary = build_dataset(words, vocabulary_size)
	print(len(dictionary))
	del words  # Hint to reduce memory.
	print('Most common words (+UNK)', count[:5])
	print('Sample data', data[:10], [reverse_dictionary[i] for i in data[:10]])

	batch, labels = generate_batch(batch_size=8, num_skips=2, skip_window=1, data=data)

	for i in range(8):
  		print(batch[i], reverse_dictionary[batch[i]],
      		'->', labels[i, 0], reverse_dictionary[labels[i, 0]])

	# Step 4: Build and train a skip-gram model.

	batch_size = 128
	embedding_size = 128  # Dimension of the embedding vector.
	skip_window = 2       # How many words to consider left and right.
	num_skips = 4         # How many times to reuse an input to generate a label.

	# We pick a random validation set to sample nearest neighbors. Here we limit the
	# validation samples to the words that have a low numeric ID, which by
	# construction are also the most frequent.
	valid_size = 16     # Random set of words to evaluate similarity on.
	valid_window = 100  # Only pick dev samples in the head of the distribution.
	valid_examples = np.random.choice(valid_window, valid_size, replace=False)
	num_sampled = 64    # Number of negative examples to sample.

	graph = tf.Graph()

	with graph.as_default():

	  # Input data.
	  train_inputs = tf.placeholder(tf.int32, shape=[batch_size])
	  train_labels = tf.placeholder(tf.int32, shape=[batch_size, 1])
	  valid_dataset = tf.constant(valid_examples, dtype=tf.int32)

	  # Ops and variables pinned to the CPU because of missing GPU implementation
	  with tf.device('/cpu:0'):
	    # Look up embeddings for inputs.
	    embeddings = tf.Variable(
	        tf.random_uniform([vocabulary_size, embedding_size], -1.0, 1.0))
	    embed = tf.nn.embedding_lookup(embeddings, train_inputs)

	    # Construct the variables for the NCE loss
	    nce_weights = tf.Variable(
	        tf.truncated_normal([vocabulary_size, embedding_size],
	                            stddev=1.0 / math.sqrt(embedding_size)))
	    nce_biases = tf.Variable(tf.zeros([vocabulary_size]))

	  # Compute the average NCE loss for the batch.
	  # tf.nce_loss automatically draws a new sample of the negative labels each
	  # time we evaluate the loss.
	  loss = tf.reduce_mean(
	      tf.nn.nce_loss(nce_weights, nce_biases, embed, train_labels,
	                     num_sampled, vocabulary_size))

	  # Construct the SGD optimizer using a learning rate of 1.0.
	  optimizer = tf.train.GradientDescentOptimizer(1.0).minimize(loss)

	  # Compute the cosine similarity between minibatch examples and all embeddings.
	  norm = tf.sqrt(tf.reduce_sum(tf.square(embeddings), 1, keep_dims=True))
	  normalized_embeddings = embeddings / norm
	  valid_embeddings = tf.nn.embedding_lookup(
	      normalized_embeddings, valid_dataset)
	  similarity = tf.matmul(
	      valid_embeddings, normalized_embeddings, transpose_b=True)

	  # Add variable initializer.
	  init = tf.initialize_all_variables()

	# Begin training.
	# num_steps = 100001

	with tf.Session(graph=graph) as session:
	  # We must initialize all variables before we use them.
	  init.run()
	  print("Initialized")

	  average_loss = 0
	  for step in xrange(num_steps):
	    batch_inputs, batch_labels = generate_batch(
	        batch_size, num_skips, skip_window, data)
	    feed_dict = {train_inputs : batch_inputs, train_labels : batch_labels}

	    # We perform one update step by evaluating the optimizer op (including it
	    # in the list of returned values for session.run()
	    _, loss_val = session.run([optimizer, loss], feed_dict=feed_dict)
	    average_loss += loss_val

	    if step % 2000 == 0:
	      if step > 0:
	        average_loss /= 2000
	      # The average loss is an estimate of the loss over the last 2000 batches.
	      print("Average loss at step ", step, ": ", average_loss)
	      average_loss = 0

	    # Note that this is expensive (~20% slowdown if computed every 500 steps)
	    if step % 10000 == 0:
	      sim = similarity.eval()
	      for i in xrange(valid_size):
	        valid_word = reverse_dictionary[valid_examples[i]]
	        top_k = 8 # number of nearest neighbors
	        nearest = (-sim[i, :]).argsort()[1:top_k+1]
	        log_str = "Nearest to %s:" % valid_word
	        for k in xrange(top_k):
	          close_word = reverse_dictionary[nearest[k]]
	          log_str = "%s %s," % (log_str, close_word)
	        print(log_str)
	  final_embeddings = normalized_embeddings.eval()
	  print(final_embeddings.shape)

	y_pred = saveTSNE()
	save("wordEMBEDDINGS/word_space/words_labels.json", "y_pred")
	save("wordEMBEDDINGS/word_space/words_vector.json", "final_embeddings")

def saveTSNE():
	try:
	  from sklearn.manifold import TSNE

	  tsne = TSNE(perplexity=30, n_components=2, init='pca', n_iter=5000)
	  plot_only = 500
	  low_dim_embs = tsne.fit_transform(final_embeddings)
	  y_pred = KMeans(n_clusters=6, random_state=170).fit_predict(low_dim_embs)
	  low_dim_embs = low_dim_embs[:plot_only,:]
	  labels = [reverse_dictionary[i] for i in xrange(plot_only)]
	  if y_pred is None:
	  	plot_with_labels(low_dim_embs, labels, filename="tsne.png")
	  else:
	  	plot_with_labels(low_dim_embs, labels, filename='tsne.png', y_pred=y_pred)

	except ImportError:
	  print("Please install sklearn, matplotlib, and scipy to visualize embeddings.")
	return y_pred

import json
def save(filename,name):
    """Salva os valores do vies e dos pesos da rede num arquivo."""
    filename = filename
    data = {name: [v.tolist() for v in final_embeddings]}
    f = open(filename, "w")
    json.dump(data, f)
    f.close()
    
def load(filename):
    """Carrega os dados de alguma rede anteriormente treinada."""
    global final_embeddings
    f = open(filename, "r")
    data = json.load(f)
    f.close()
    final_embeddings = [np.array(w) for w in data["final_embeddings"]]
    return np.asarray(final_embeddings)

if __name__ == '__main__':

	vocabulary_size = 12000
	# word2vec("base_de_dados.zip",vocabulary_size, 50001)
	final_embeddings = load("wordEMBEDDINGS/wordspace/words_vector.json")
	words = read_data("wordEMBEDDINGS/dataset/embeddings_data.zip")
	data, count, dictionary, reverse_dictionary = build_dataset(words, vocabulary_size)
	del words

# 	ids = [winterfell
# dreadfort
# castle black
# craster's keep
# mole's town
# moat cailin
# the twins
# the eyrie
# braavos
# kings landing
# inn at the crossroads
# pyke
# dragonstone
# sunspear]
	words = [dictionary["cersei"],dictionary["arya"],
			dictionary["jaime"],dictionary["tyrion"], 
			dictionary["theon"], dictionary["jon"],
			dictionary["sansa"],dictionary["tywin"],
			dictionary["brienne"],dictionary["hodor"],
			dictionary["joffrey"],dictionary["ramsay"],
			dictionary["robert"],dictionary["daenerys"],
			dictionary["eddard"],dictionary["oberyn"],
			dictionary["bran"],dictionary["jorah"],
			dictionary["myrcella"],dictionary["melisandre"],
			dictionary["bronn"],dictionary["margaery"]]
	
	y_pred = saveTSNE()
	# target = final_embeddings[words]
	# dist = final_embeddings.dot(target.T)
	# # nearest = dist.argsort()[-10:]
	# # final_embeddings[word]
	# print(dist.shape)
	# print(dist[nearest])
	for i in words:
		valid_word = reverse_dictionary[i]
		target = final_embeddings[i]
		he = final_embeddings[dictionary['he']] 
		she = final_embeddings[dictionary['she']]
		dist = final_embeddings.dot(target.T)
		dist = dist*dist
	  	nearest = dist[:].argsort()[-20:]
	  	# log_str = "Nearest to %s:" % valid_word
	   #      for k in xrange(19):
	   #        close_word = reverse_dictionary[nearest[-k-1]]
	   #        log_str = "%s %s," % (log_str, close_word)
	   #      print(log_str)
		hedist = target.dot(he.T)
		hedist *= hedist
		shedist = target.dot(she.T)
		shedist *= shedist
		log_str = "%s Class: %s" % (valid_word,y_pred[i])
		if hedist > shedist:
			log_str += " macho"
		else:
			log_str += " femea"
		print(log_str)
