from __future__ import print_function
import numpy as np
import csv, datetime, time, json
from zipfile import ZipFile
from os.path import expanduser, exists
from keras.preprocessing.text import Tokenizer
from keras.preprocessing.sequence import pad_sequences
from keras.models import Model
from keras.layers import Input, TimeDistributed, Dense, Lambda, concatenate, Dropout, BatchNormalization
from keras.layers.embeddings import Embedding
from keras.regularizers import l2
from keras.callbacks import Callback, ModelCheckpoint
from keras.utils.data_utils import get_file
from keras import backend as K
from sklearn.model_selection import train_test_split
import heapq
import operator
# Initialize global variables
KERAS_DATASETS_DIR = expanduser('/Users/wqc/Desktop/keras-quora-question-pairs-master/')

QUESTION_PAIRS_FILE = 'keras_training_data.json'
TAGS_FILE = 'alltags.json'
GLOVE_ZIP_FILE_URL = 'http://nlp.stanford.edu/data/glove.840B.300d.zip'
GLOVE_ZIP_FILE = 'glove.840B.300d.zip'
GLOVE_FILE = 'glove.840B.300d.txt'
Q1_TRAINING_DATA_FILE = 'q1_train.npy'
Q2_TRAINING_DATA_FILE = 'q2_train.npy'
LABEL_TRAINING_DATA_FILE = 'label_train.npy'
WORD_EMBEDDING_MATRIX_FILE = 'word_embedding_matrix.npy'
NB_WORDS_DATA_FILE = 'nb_words.json'
MAX_NB_WORDS = 220000
MAX_SEQUENCE_LENGTH = 25
EMBEDDING_DIM = 300
MODEL_WEIGHTS_FILE = 'stack_pairs_weights.h5'
VALIDATION_SPLIT = 0.1
TEST_SPLIT = 0.1
RNG_SEED = 13371447
NB_EPOCHS = 25
DROPOUT = 0.2
BATCH_SIZE = 32
OPTIMIZER = 'adam'


def create_model():
    if exists(Q1_TRAINING_DATA_FILE) and exists(Q2_TRAINING_DATA_FILE) and exists(LABEL_TRAINING_DATA_FILE) and exists(
            NB_WORDS_DATA_FILE) and exists(WORD_EMBEDDING_MATRIX_FILE):
        # Then load them
        q1_data = np.load(open(Q1_TRAINING_DATA_FILE, 'rb'))
        q2_data = np.load(open(Q2_TRAINING_DATA_FILE, 'rb'))
        labels = np.load(open(LABEL_TRAINING_DATA_FILE, 'rb'))
        word_embedding_matrix = np.load(open(WORD_EMBEDDING_MATRIX_FILE, 'rb'))
        with open(NB_WORDS_DATA_FILE, 'r') as f:
            nb_words = json.load(f)['nb_words']
    else:
        # Else download and extract questions pairs data
        # if not exists(KERAS_DATASETS_DIR + QUESTION_PAIRS_FILE):
        #   get_file(QUESTION_PAIRS_FILE, QUESTION_PAIRS_FILE_URL)

        print("Processing", QUESTION_PAIRS_FILE)

        question1 = []
        question2 = []
        is_duplicate = []
        with open(KERAS_DATASETS_DIR + QUESTION_PAIRS_FILE, encoding='utf-8') as jsondata:
            file = json.load(jsondata)
            flag = 0
            for row in file:
                if row['is_duplicate'] != 0 and row['is_duplicate'] != 1:
                    pass
                else:
                    question1.append(row['question1'])
                    question2.append(row['question2'])
                    is_duplicate.append(row['is_duplicate'])

        print('Question pairs: %d' % len(question1))

        # Build tokenized word index
        questions = question1 + question2
        tokenizer = Tokenizer(num_words=MAX_NB_WORDS)
        tokenizer.fit_on_texts(questions)
        question1_word_sequences = tokenizer.texts_to_sequences(question1)
        question2_word_sequences = tokenizer.texts_to_sequences(question2)
        word_index = tokenizer.word_index

        print("Words in index: %d" % len(word_index))

        # Download and process GloVe embeddings
        '''if not exists(KERAS_DATASETS_DIR + GLOVE_ZIP_FILE):
            zipfile = ZipFile(get_file(GLOVE_ZIP_FILE, GLOVE_ZIP_FILE_URL))
            zipfile.extract(GLOVE_FILE, path=KERAS_DATASETS_DIR)
            '''
        print("Processing", GLOVE_FILE)

        embeddings_index = {}
        with open(KERAS_DATASETS_DIR + GLOVE_FILE, encoding='utf-8') as f:
            for line in f:
                values = line.split(' ')
                word = values[0]
                embedding = np.asarray(values[1:], dtype='float32')
                embeddings_index[word] = embedding

        print('Word embeddings: %d' % len(embeddings_index))

        # Prepare word embedding matrix
        nb_words = min(MAX_NB_WORDS, len(word_index))
        word_embedding_matrix = np.zeros((nb_words + 1, EMBEDDING_DIM))
        for word, i in word_index.items():
            if i > MAX_NB_WORDS:
                continue
            embedding_vector = embeddings_index.get(word)
            if embedding_vector is not None:
                word_embedding_matrix[i] = embedding_vector

        print('Null word embeddings: %d' % np.sum(np.sum(word_embedding_matrix, axis=1) == 0))

        # Prepare training data tensors
        q1_data = pad_sequences(question1_word_sequences, maxlen=MAX_SEQUENCE_LENGTH)
        q2_data = pad_sequences(question2_word_sequences, maxlen=MAX_SEQUENCE_LENGTH)
        labels = np.array(is_duplicate, dtype=int)
        print('Shape of question1 data tensor:', q1_data.shape)
        print('Shape of question2 data tensor:', q2_data.shape)
        print('Shape of label tensor:', labels.shape)

        # Persist training and configuration data to files
        np.save(open(Q1_TRAINING_DATA_FILE, 'wb'), q1_data)
        np.save(open(Q2_TRAINING_DATA_FILE, 'wb'), q2_data)
        np.save(open(LABEL_TRAINING_DATA_FILE, 'wb'), labels)
        np.save(open(WORD_EMBEDDING_MATRIX_FILE, 'wb'), word_embedding_matrix)
        with open(NB_WORDS_DATA_FILE, 'w') as f:
            json.dump({'nb_words': nb_words}, f)

    # Partition the dataset into train and test sets
    X = np.stack((q1_data, q2_data), axis=1)
    y = labels
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=TEST_SPLIT, random_state=RNG_SEED)
    Q1_train = X_train[:, 0]
    Q2_train = X_train[:, 1]
    Q1_test = X_test[:, 0]
    Q2_test = X_test[:, 1]

    # Define the model
    question1 = Input(shape=(MAX_SEQUENCE_LENGTH,))
    question2 = Input(shape=(MAX_SEQUENCE_LENGTH,))

    q1 = Embedding(nb_words + 1,
                   EMBEDDING_DIM,
                   weights=[word_embedding_matrix],
                   input_length=MAX_SEQUENCE_LENGTH,
                   trainable=False)(question1)
    q1 = TimeDistributed(Dense(EMBEDDING_DIM, activation='relu'))(q1)
    q1 = Lambda(lambda x: K.max(x, axis=1), output_shape=(EMBEDDING_DIM,))(q1)

    q2 = Embedding(nb_words + 1,
                   EMBEDDING_DIM,
                   weights=[word_embedding_matrix],
                   input_length=MAX_SEQUENCE_LENGTH,
                   trainable=False)(question2)
    q2 = TimeDistributed(Dense(EMBEDDING_DIM, activation='relu'))(q2)
    q2 = Lambda(lambda x: K.max(x, axis=1), output_shape=(EMBEDDING_DIM,))(q2)

    merged = concatenate([q1,q2])
    merged = Dense(200, activation='relu')(merged)
    merged = Dropout(DROPOUT)(merged)
    merged = BatchNormalization()(merged)
    merged = Dense(200, activation='relu')(merged)
    merged = Dropout(DROPOUT)(merged)
    merged = BatchNormalization()(merged)
    merged = Dense(200, activation='relu')(merged)
    merged = Dropout(DROPOUT)(merged)
    merged = BatchNormalization()(merged)
    merged = Dense(200, activation='relu')(merged)
    merged = Dropout(DROPOUT)(merged)
    merged = BatchNormalization()(merged)

    is_duplicate = Dense(1, activation='sigmoid')(merged)

    model = Model(inputs=[question1,question2], outputs=is_duplicate)
    model.compile(loss='binary_crossentropy', optimizer=OPTIMIZER, metrics=['accuracy'])

    return model

def load_model(path):
    model = create_model()
    model.load_weights(path)
    return model
    
def train_model(model):
    model.compile(loss='binary_crossentropy', optimizer=OPTIMIZER, metrics=['accuracy'])

    # Train the model, checkpointing weights with best validation accuracy
    print("Starting training at", datetime.datetime.now())
    t0 = time.time()
    callbacks = [ModelCheckpoint(MODEL_WEIGHTS_FILE, monitor='val_acc', save_best_only=True)]
    history = model.fit([Q1_train, Q2_train],
                    y_train,
                    epochs=NB_EPOCHS,
                    validation_split=VALIDATION_SPLIT,
                    verbose=2,
                    batch_size=BATCH_SIZE,
                    callbacks=callbacks)
    t1 = time.time()
    print("Training ended at", datetime.datetime.now())
    print("Minutes elapsed: %f" % ((t1 - t0) / 60.))

    # Print best validation accuracy and epoch
    max_val_acc, idx = max((val, idx) for (idx, val) in enumerate(history.history['val_acc']))
    print('Maximum validation accuracy = {0:.4f} (epoch {1:d})'.format(max_val_acc, idx+1))

'''    # Evaluate the model with best validation accuracy on the test partition
    model.load_weights(MODEL_WEIGHTS_FILE)
    loss, accuracy = model.evaluate([Q1_test, Q2_test], y_test, verbose=0)
    print('Test loss = {0:.4f}, test accuracy = {1:.4f}'.format(loss, accuracy))

'''

def test(model,test_path):

    print("Processing", test_path)

    question1 = []
    question2 = []
    is_duplicate = []
    with open( test_path, encoding='utf-8') as jsondata:
        file = json.load(jsondata)
        for row in file:
            if row['is_duplicate'] != 0 and row['is_duplicate'] != 1:
                pass
            else:
                question1.append(row['question1'])
                question2.append(row['question2'])
                is_duplicate.append(row['is_duplicate'])

    print('Question pairs: %d' % len(question1))
    questions = question1 + question2
    tokenizer = Tokenizer(num_words=MAX_NB_WORDS)
    tokenizer.fit_on_texts(questions)
    question1_word_sequences = tokenizer.texts_to_sequences(question1)
    question2_word_sequences = tokenizer.texts_to_sequences(question2)

    q1_data = pad_sequences(question1_word_sequences, maxlen=MAX_SEQUENCE_LENGTH)
    q2_data = pad_sequences(question2_word_sequences, maxlen=MAX_SEQUENCE_LENGTH)   

    X = np.stack((q1_data, q2_data), axis=1)
    y = np.array(is_duplicate, dtype=int)
    Q1_test = X[:, 0]
    Q2_test = X[:, 1]
    results = model.predict([Q1_test, Q2_test], batch_size = 32, verbose=0)
    
    #loss, accuracy = model.evaluate([Q1_test, Q2_test], y, verbose=0)
    #print('Test loss = {0:.4f}, test accuracy = {1:.4f}'.format(loss, accuracy))
    print("Finishing predict")
    TP = 0
    TN = 0
    FP = 0
    FN = 0
    for i in range(len(is_duplicate)):
        if i % 10000 == 0: print(i)

        if round(results[i][0]) == 1 and is_duplicate[i] == 1:
            TP += 1
        elif round(results[i][0]) == 0 and is_duplicate[i] == 0:
            TN += 1
        elif round(results[i][0]) == 0 and is_duplicate[i] == 1:
            FN += 1
        elif round(results[i][0]) == 1 and is_duplicate[i] == 0:
            FP += 1

    N = len(is_duplicate)
    accuracy = (TP + TN) / N
    precision = TP / (TP + FP)
    recall = TP / (TP + FN)
    f1 = (2 * precision * recall) / (precision + recall)
    print("Accuracy: ", accuracy)
    print("Precision: ", precision)
    print("Recall: ", recall)
    print("F1 score: ", f1)


def evaluate(model):
    print("Processing", QUESTION_PAIRS_FILE)

    question1 = []
    question2 = []
    is_duplicate = []
    with open(QUESTION_PAIRS_FILE, encoding='utf-8') as jsondata:
        file = json.load(jsondata)
        for row in file:
            if row['is_duplicate'] != 0 and row['is_duplicate'] != 1:
                pass
            else:
                question1.append(row['question1'])
                question2.append(row['question2'])
                is_duplicate.append(row['is_duplicate'])

    print('Question pairs: %d' % len(question1))
    questions = question1 + question2
    tokenizer = Tokenizer(num_words=MAX_NB_WORDS)
    tokenizer.fit_on_texts(questions)
    question1_word_sequences = tokenizer.texts_to_sequences(question1)
    question2_word_sequences = tokenizer.texts_to_sequences(question2)

    q1_data = pad_sequences(question1_word_sequences, maxlen=MAX_SEQUENCE_LENGTH)
    q2_data = pad_sequences(question2_word_sequences, maxlen=MAX_SEQUENCE_LENGTH)

    X = np.stack((q1_data, q2_data), axis=1)
    y = np.array(is_duplicate, dtype=int)
    Q1_test = X[:, 0]
    Q2_test = X[:, 1]
    results = model.predict([Q1_test, Q2_test], batch_size = 32, verbose=0)

    #loss, accuracy = model.evaluate([Q1_test, Q2_test], y, verbose=0)
    #print('Test loss = {0:.4f}, test accuracy = {1:.4f}'.format(loss, accuracy))

    print("Finishing predict")
    TP = 0
    TN = 0
    FP = 0
    FN = 0
    for i in range(len(is_duplicate)):
        if i % 10000 == 0: print(i)

        if round(results[i][0]) == 1 and is_duplicate[i] == 1:
            TP += 1
        elif round(results[i][0]) == 0 and is_duplicate[i] == 0:
            TN += 1
        elif round(results[i][0]) == 0 and is_duplicate[i] == 1:
            FN += 1
        elif round(results[i][0]) == 1 and is_duplicate[i] == 0:
            FP += 1

    N = len(is_duplicate)
    accuracy = (TP + TN) / N
    precision = TP / (TP + FP)
    recall = TP / (TP + FN)
    f1 = (2 * precision * recall) / (precision + recall)
    print("Accuracy: ", accuracy)
    print("Precision: ", precision)
    print("Recall: ", recall)
    print("F1 score: ", f1)

tags = []
def prepare_tags():
    with open(KERAS_DATASETS_DIR + TAGS_FILE, encoding='utf-8') as jsondata:
            tagfile = json.load(jsondata)
            flag = 0
            for row in tagfile:
                tags.append(row['tagname'])
    if 'ada' in tags:
        print("in tags")


def recommendation_k_search(model, k, query_file ,tagname):

    print("Processing", query_file)

    query1 = []
    G_T = []
    question2 = []

    with open(query_file + '.json', encoding='utf-8') as jsondata:
        file = json.load(jsondata)
        for row in file:
            query1.append(row['question1'])
            G_T.append(row['question2'])
            question2.append(row['question2'])

    print("Processing", tagname)

    question2 = []

    with open( tagname+'.json', encoding='utf-8') as jsondata:
        file = json.load(jsondata)
        for row in file:
            question2.append(row['Title'])

    for i in G_T:
        if i in question2:
            pass
        else:
            print(i)
            question2.append(i)

    questions = query1 + question2
    tokenizer = Tokenizer(num_words=MAX_NB_WORDS)
    tokenizer.fit_on_texts(questions)
    question2_word_sequences = tokenizer.texts_to_sequences(question2)
    q2_data = pad_sequences(question2_word_sequences, maxlen=MAX_SEQUENCE_LENGTH)

    print("Finishing prepared\n")

    for index in range(len(query1)):

        my_question = query1[index]
        question1 = []
        for leng in range(len(question2)):
            question1.append(my_question)
        print('This is query %d' % index)

        question1_word_sequences = tokenizer.texts_to_sequences(question1)
        q1_data = pad_sequences(question1_word_sequences, maxlen=MAX_SEQUENCE_LENGTH)
        X = np.stack((q1_data, q2_data), axis=1)
        Q1_test = X[:, 0]
        Q2_test = X[:, 1]
        print("Start Predicting")
        results = model.predict([Q1_test, Q2_test], batch_size = 32, verbose=0)
        #print(results,"\n\n\n\n")

        print("Start ranking")
        result_match_sentence = {}
        for i in range(len(question2)):
            result_match_sentence[question2[i]] = results[i][0]

        knn_recommendation_sentence = heapq.nlargest(10, result_match_sentence )

        print(knn_recommendation_sentence)
        newone = {}
        for i in range(k):
            newone[knn_recommendation_sentence[i]]= result_match_sentence[knn_recommendation_sentence[i]]

        l = sorted(newone.items(), key=operator.itemgetter(1), reverse=True)
        print(l)
        print("====================================")
        print("\n\n")
        print(my_question)
        print("\n\n")
        for lll in l:
            print(lll[1], "   ",lll[0])
        print("\n\n\n\n")
        print("====================================")

        print("Ground Truth is %s" % G_T[index])


def check_G_T (model, query_file):

    print("Processing", query_file)

    question1 = []
    question2 = []
    with open(query_file + '.json', encoding='utf-8') as jsondata:
        file = json.load(jsondata)
        for row in file:
            question1.append(row['question1'])
            question2.append(row['question2'])

    print("Processing", query_file)
    questions = question1 + question2
    tokenizer = Tokenizer(num_words=MAX_NB_WORDS)
    tokenizer.fit_on_texts(questions)
    question1_word_sequences = tokenizer.texts_to_sequences(question1)
    question2_word_sequences = tokenizer.texts_to_sequences(question2)

    q1_data = pad_sequences(question1_word_sequences, maxlen=MAX_SEQUENCE_LENGTH)
    q2_data = pad_sequences(question2_word_sequences, maxlen=MAX_SEQUENCE_LENGTH)

    X = np.stack((q1_data, q2_data), axis=1)
    Q1_test = X[:, 0]
    Q2_test = X[:, 1]
    results = model.predict([Q1_test, Q2_test], batch_size=32, verbose=0)
    for i in results:
        print(i)

model = load_model('stack_pairs_weights.h5')
#recommendation_k_search(model, 10, 'facebook_query', 'facebook')
#check_G_T(model,'facebook_query')





#my_question = 'How to start with Ada'
#my_question = 'How to compile ada program in linux'
#my_question = 'how to store data into mysql database with python'
#recommendation_k_search(model,20,'python+database+mysql')

#model = load_model('stack_pairs_weights.h5')
#evaluate(model)
test(model,'testing_query.json')
