import pandas as pd
import numpy as np

import glob
import os
from pathlib import Path

from sklearn.model_selection import train_test_split
from sklearn import preprocessing
from sklearn.utils import compute_class_weight
from sklearn.metrics import classification_report, confusion_matrix
import scipy

import tensorflow as tf

from keras.callbacks import ModelCheckpoint, TensorBoard, EarlyStopping
from keras.preprocessing.image import img_to_array, load_img, ImageDataGenerator
from keras.optimizers import SGD
from keras.applications.imagenet_utils import decode_predictions
from keras.layers import Activation, Dense, GlobalAveragePooling2D, GlobalMaxPooling2D
from keras.models import Model
from keras.utils import to_categorical
from keras import optimizers, layers
from keras import backend as K

#from efficientnet import EfficientNetB4
import efficientnet.keras as efn

def do_train():
    base_dir = '/gpfs/gpfs0/deep/data/Otoliths_cod/codotoliths/'

    dirs = set()

    df_cod = pd.DataFrame(columns=['age', 'path'])

    max_dataset_size = 1029#6330
    new_shape = (380, 380, 3)
    IMG_SHAPE = (380, 380)
    rb_imgs = np.empty(shape=(max_dataset_size,)+new_shape)
    os.environ["CUDA_VISIBLE_DEVICES"]="1"
    tensorboard_path= './tensorboard_cod_age_softmax2'
    checkpoint_path = './checkpoints_cod_age_softmax2/cod_oto_efficientnetB4.{epoch:03d}-{val_loss:.2f}.hdf5'

    add_count = 0
    for filename in Path(base_dir).glob('**/*.JPG'):
        filepath =str(filename)
        dirname = os.path.dirname(filepath)
        if ( dirname not in dirs ):
            dirs.add(dirname)
            begin_age = filepath.find('age')
            age = filepath[begin_age+3:begin_age+5]
            age = int(age)
            pil_img = load_img(filepath, target_size=IMG_SHAPE, grayscale=False)
            array_img = img_to_array(pil_img, data_format='channels_last')
            rb_imgs[add_count] = array_img
            df_cod = df_cod.append({'age':age, 'path':filepath}, ignore_index=True)
            add_count +=1
            #print(add_count)

    a_batch_size = 12
    age = df_cod.age.values


    early_stopper = EarlyStopping(patience=20)
    train_datagen = ImageDataGenerator(
        zca_whitening=True,
        width_shift_range=0.,
        height_shift_range=0., #20,
        zoom_range=0.,
        rotation_range=360,
        horizontal_flip=False,
        vertical_flip=True,
        rescale=1./255)

    #EXPERIMENT_FOLDER_PATH = os.path.join(parent_dir_of_file, f"reports/experiments/{EXPERIMENT_NAME}")
    DEFAULT_CONFIG = {
        "model": "basiccnn",
        "method": "bayesian_optimization",
        "train_set_size": 1029,
        "opt_samples": 3,
        "opt_last_n_epochs": 3,
        "opt_initial_points": 10,
        "child_epochs": 50,
        "child_first_train_epochs": 0,
        "child_batch_size": 64,
        "pre_aug_weights_path": "pre_aug_weights.h5"
    }
    deepaug = DeepAugment(rb_imgs, age, config=DEFAULT_CONFIG)

    train_idx, val_idx, test_idx = train_validate_test_split( range(0, len(rb_imgs)) )
    train_rb_imgs = np.empty(shape=(len(train_idx),)+new_shape)
    train_age = []
    for i in range(0, len(train_idx)):
        train_rb_imgs[i] = rb_imgs[train_idx[i]]
        train_age.append(age[train_idx[i]])

    val_rb_imgs = np.empty(shape=(len(val_idx),)+new_shape)
    val_age = []
    for i in range(0, len(val_idx)):
        val_rb_imgs[i] = rb_imgs[val_idx[i]]
        val_age.append(age[val_idx[i]])

    test_rb_imgs = np.empty(shape=(len(test_idx),)+new_shape)
    test_age = []
    for i in range(0, len(test_idx)):
        test_rb_imgs[i] = rb_imgs[test_idx[i]]
        test_age.append(age[test_idx[i]])

    train_age = np.vstack(train_age)
    val_age = np.vstack(val_age)
    test_age = np.vstack(test_age)

    val_rb_imgs = np.multiply(val_rb_imgs, 1./255)
    test_rb_imgs = np.multiply(test_rb_imgs, 1./255)

    train_generator = train_datagen.flow(train_rb_imgs, train_age, batch_size= a_batch_size)

    efn.EfficientNetB0(weights='imagenet')
    rgb_efficientNetB4 = EfficientNetB4(include_top=False, weights='imagenet', input_shape=new_shape, classes=2)
    z = dense1_linear_output( rgb_efficientNetB4 )
    scales = Model(inputs=rgb_efficientNetB4.input, outputs=z)

    learning_rate=0.0001
    adam = optimizers.Adam(lr=learning_rate)

    for layer in scales.layers:
        layer.trainable = True

    scales.compile(loss='mse', optimizer=adam, metrics=['accuracy','mse', 'mape'] )
    tensorboard, checkpointer = get_checkpoint_tensorboard(tensorboard_path, checkpoint_path)

    classWeight = None

    history_callback = scales.fit_generator(train_generator,
            steps_per_epoch=1600,
            epochs=150,
            callbacks=[early_stopper, tensorboard, checkpointer],
            validation_data=(val_rb_imgs, val_age),
            class_weight=classWeight)

    test_metrics = scales.evaluate(x=test_rb_imgs, y=test_age)
    print("test metric:"+str(scales.metrics_names))
    print("test metrics:"+str(test_metrics))

    print("precision, recall, f1")
    y_pred_test = scales.predict(test_rb_imgs, verbose=1)
    y_pred_test_bool = np.argmax(y_pred_test, axis=1)
    y_true_bool = np.argmax(test_age, axis=1)
    #np.argmax inverse of to_categorical
    argmax_test = np.argmax(test_age, axis=1)
    unique, counts = np.unique(argmax_test, return_counts=True)
    print("test ocurrence of each class:"+str(dict(zip(unique, counts))))

    print("cslassification_report")
    print(classification_report(y_true_bool, y_pred_test_bool))
    print("confusion matrix")
    print(str(confusion_matrix(y_true_bool, y_pred_test_bool)))

def base_output(model):
    z = model.output
    z = GlobalMaxPooling2D()(z)
    return z

def dense1_linear_output(gray_model):
    z = base_output(gray_model)
    z = Dense(1, activation='linear')(z)
    return z

def get_checkpoint_tensorboard(tensorboard_path, checkpoint_path):

    tensorboard = TensorBoard(log_dir=tensorboard_path)
    checkpointer = ModelCheckpoint(
        filepath = checkpoint_path,
        verbose = 1,
        save_best_only = True,
        save_weights_only = False)
    return tensorboard, checkpointer

def train_validate_test_split(pairs, validation_set_size = 0.15, test_set_size = 0.15, a_seed = 8):
    """ split pairs into 3 set, train-, validation-, and test-set
        1 - (validation_set_size + test_set_size) = % training set size
    >>> import pandas as pd
    >>> import numpy as np
    >>> data = np.array([np.arange(10)]*2).T  # 2 columns for x, y, and one for index
    >>> df_ = pd.DataFrame(data, columns=['x', 'y'])
    >>> train_x, val_x, test_x = \
             train_validate_test_split( df_, validation_set_size = 0.2, test_set_size = 0.2, a_seed = 1 )
    >>> train_x['x'].values
    array([0, 3, 1, 7, 8, 5])
    >>> val_x['x'].values
    array([4, 6])
    >>> test_x['x'].values
    array([2, 9])
    """
    validation_and_test_set_size = validation_set_size + test_set_size
    validation_and_test_split = validation_set_size / (test_set_size+validation_set_size)

    df_train_x, df_notTrain_x = train_test_split(pairs, test_size = validation_and_test_set_size, random_state = a_seed)

    df_test_x, df_val_x = train_test_split(df_notTrain_x, test_size = validation_and_test_split, random_state = a_seed)

    return df_train_x, df_val_x, df_test_x

if __name__ == '__main__':
    do_train()
