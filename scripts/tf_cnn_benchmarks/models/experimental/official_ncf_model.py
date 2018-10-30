# Copyright 2018 The TensorFlow Authors. All Rights Reserved.
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
"""Wrap the official recommendation model in a tf_cnn_benchmarks Model.

This allows the recommendation NCF model to be used in tf_cnn_benchmarks.
Currently, the implementation is fairly hacky, because tf_cnn_benchmarks is
intended to be used only with CNNs.

Only synthetic data with 1 GPU is currently supported.
"""

import tensorflow as tf

from models import model


# Obtained by running the official NCF model with the following command:
#     python ncf_main.py  --dataset ml-20m
# and printing the number of users and items here:
# https://github.com/tensorflow/models/blob/d089975f630a8a01be63e45ef08a31be14bb96b4/official/recommendation/data_preprocessing.py#L68
_NUM_USERS_20M = 138493
_NUM_ITEMS_20M = 26744


# TODO(reedwm): Support multi-GPU. Currently keras layers, which this model
# uses, ignore variable_scopes, which we rely on for multi-GPU support.
# TODO(reedwm): Support real data. This will require a significant refactor.
# TODO(reedwm): Support fp16.
# TODO(reedwm): All-reduce IndexedSlices more effectively.
# TODO(reedwm): Support the 1M variant of this model.


class NcfModel(model.Model):
  r"""A model.Model wrapper around the official NCF recommendation model.

  To do an NCF run with synthetic data that roughly matches what the official
  model does, run:

  python tf_cnn_benchmarks.py --optimizer=adam --model=ncf --batch_size=65536 \
      --weight_decay=0 --sparse_to_dense_grads
  """

  def __init__(self, params=None):
    super(NcfModel, self).__init__(
        'official_ncf', batch_size=2048, learning_rate=0.0005,
        fp16_loss_scale=128, params=params)
    if self.data_type != tf.float32:
      raise ValueError('NCF model only supports float32 for now.')

  def build_network(self, inputs, phase_train=True, nclass=1001):
    try:
      from official.recommendation import neumf_model  # pylint: disable=g-import-not-at-top
    except ImportError as e:
      if 'neumf_model' not in e.message:
        raise
      raise ImportError('To use the experimental NCF model, you must clone the '
                        'repo https://github.com/tensorflow/models and add '
                        'tensorflow/models to the PYTHONPATH.')
    del nclass

    users, items, _ = inputs
    params = {
        'num_users': _NUM_USERS_20M,
        'num_items': _NUM_ITEMS_20M,
        'model_layers': (256, 256, 128, 64),
        'mf_dim': 64,
        'mf_regularization': 0,
        'mlp_reg_layers': (0, 0, 0, 0),
        'use_tpu': False
    }
    keras_model = neumf_model.construct_model(users, items, params)
    return model.BuildNetworkResult(logits=keras_model.output, extra_info=None)

  def loss_function(self, inputs, build_network_result):
    logits = build_network_result.logits

    # Softmax with the first column of ones is equivalent to sigmoid.
    # TODO(reedwm): Actually, the first column should be zeros to be equivalent
    # to sigmoid. But, we keep it at ones to match the official models.
    logits = tf.concat([tf.ones(logits.shape, dtype=logits.dtype), logits],
                       axis=1)

    return tf.losses.sparse_softmax_cross_entropy(
        labels=inputs[2],
        logits=logits
    )

  def get_synthetic_inputs(self, input_name, nclass):
    """Returns the ops to generate synthetic inputs and labels."""
    def users_init_val():
      return tf.random_uniform((self.batch_size,), minval=0,
                               maxval=_NUM_USERS_20M, dtype=tf.int32)
    users = tf.Variable(users_init_val, dtype=tf.int32, trainable=False,
                        collections=[tf.GraphKeys.LOCAL_VARIABLES],
                        name='synthetic_users')
    def items_init_val():
      return tf.random_uniform((self.batch_size,), minval=0,
                               maxval=_NUM_ITEMS_20M, dtype=tf.int32)
    items = tf.Variable(items_init_val, dtype=tf.int32, trainable=False,
                        collections=[tf.GraphKeys.LOCAL_VARIABLES],
                        name='synthetic_items')

    def labels_init_val():
      return tf.random_uniform((self.batch_size,), minval=0, maxval=2,
                               dtype=tf.int32)
    labels = tf.Variable(labels_init_val, dtype=tf.int32, trainable=False,
                         collections=[tf.GraphKeys.LOCAL_VARIABLES],
                         name='synthetic_labels')

    return [users, items, labels]

  def get_input_shapes(self, subset):
    del subset
    return [[self.batch_size], [self.batch_size], [self.batch_size]]

  def get_input_data_types(self, subset):
    del subset
    return [self.int32, tf.int32, tf.int32]
