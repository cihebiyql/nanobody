# coding=utf-8
# Copyright 2018 The Google AI Language Team Authors.
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


from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import csv
import tokenization
import tensorflow as tf


class InputExample(object):
  def __init__(self, guid, text_a, cdr_number, label=None):
    """Constructs a InputExample.

    Args:
      guid: Unique id for the example.
      text_a: string. The untokenized text of the first sequence. For single
        sequence tasks, only this sequence must be specified.
      CDR_number: string. The untokenized text of the CDR number
      label: (Optional) string. The label of the example. This should be
        specified for train and dev examples, but not for test examples.
    """
    self.guid = guid
    self.text_a = text_a
    self.cdr_number = cdr_number
    self.label = label

class InputFeatures(object):
  """A single set of features of data."""

  def __init__(self,
               input_ids,
               label_id,
               cdr_number_ids,
               is_real_example=True):
    self.input_ids = input_ids
    self.label_id = label_id
    self.cdr_number_ids = cdr_number_ids
    self.is_real_example = is_real_example

class DataProcessor(object):
  """Base class for data converters for sequence classification data sets."""

  def get_train_examples(self, data_dir):
    """Gets a collection of `InputExample`s for the train set."""
    raise NotImplementedError()

  def get_dev_examples(self, data_dir):
    """Gets a collection of `InputExample`s for the dev set."""
    raise NotImplementedError()

  def get_test_examples(self, data_dir):
    """Gets a collection of `InputExample`s for prediction."""
    raise NotImplementedError()

  def get_labels(self):
    """Gets the list of labels for this data set."""
    raise NotImplementedError()

  @classmethod
  def _read_tsv(cls, input_file, quotechar=None):
    """Reads a tab separated value file."""
    with tf.gfile.Open(input_file, "r") as f:
      reader = csv.reader(f, delimiter="\t", quotechar=quotechar)
      lines = []
      for line in reader:
        lines.append(line)
      return lines

class CDR_Ag_Processor(DataProcessor):
  def get_examples(self, file_path):
    """See base class."""
    return self._create_examples(
        self._read_tsv(file_path))

  def get_labels(self):
    """See base class."""
    return ["0", "1"]

  def _create_examples(self, lines):
    """Creates examples for the training and dev sets."""
    examples = []
    for (i, line) in enumerate(lines):
      set_type = tokenization.convert_to_unicode(line[0])
      ID = tokenization.convert_to_unicode(line[1])
      guid = "%s-%s" % (set_type, ID)
      label = tokenization.convert_to_unicode(line[2])
      text_a = tokenization.convert_to_unicode(line[3])
      cdr_number = tokenization.convert_to_unicode(line[4])

      examples.append(
          InputExample(guid=guid, text_a=text_a, cdr_number=cdr_number, label=label))
    return examples

def convert_single_example(ex_index, example, label_list, cdr_number_list , max_seq_length,
                           tokenizer):
  """Converts a single `InputExample` into a single `InputFeatures`."""

  label_map = {}
  for (i, label) in enumerate(label_list):
    label_map[label] = i

  cdr_number_map = {}
  for (i, CDR_number) in enumerate(cdr_number_list):
    cdr_number_map[CDR_number] = i

  tokens_a = tokenizer.tokenize(example.text_a)

  if len(tokens_a) > max_seq_length:
      tokens_a = tokens_a[0:max_seq_length]

  tokens = []
  cdr_number_ids = []

  for (i, token) in enumerate(tokens_a):
    tokens.append(token)
    cdr_number_ids.append(cdr_number_map[example.cdr_number])

  input_ids = tokenizer.convert_tokens_to_ids(tokens)

  # Zero-pad up to the sequence length.
  while len(input_ids) < max_seq_length:
    input_ids.append(0)
    cdr_number_ids.append(0)

  assert len(input_ids) == max_seq_length
  assert len(cdr_number_ids) == max_seq_length

  label_id = label_map[example.label]
  if ex_index < 5:
    tf.logging.info("*** Example ***")
    tf.logging.info("guid: %s" % (example.guid))
    tf.logging.info("tokens: %s" % " ".join(
        [tokenization.printable_text(x) for x in tokens]))
    tf.logging.info("input_ids: %s" % " ".join([str(x) for x in input_ids]))
    tf.logging.info("label: %s (id = %d)" % (example.label, label_id))
    tf.logging.info("CDR_number: %s" % " ".join([str(x) for x in cdr_number_ids]))

  feature = InputFeatures(
      input_ids=input_ids,
      label_id=label_id,
      cdr_number_ids=cdr_number_ids,
      is_real_example=True)

  return feature

def convert_examples_to_features(examples, label_list, cdr_number_list, max_seq_length,
                                 tokenizer):
  """Convert a set of `InputExample`s to a list of `InputFeatures`."""

  features = []
  for (ex_index, example) in enumerate(examples):
    if ex_index % 10000 == 0:
      tf.logging.info("Writing example %d of %d" % (ex_index, len(examples)))

    feature = convert_single_example(ex_index, example, label_list, cdr_number_list,
                                     max_seq_length, tokenizer)

    features.append(feature)
  return features


def main(_):
  tf.logging.set_verbosity(tf.logging.INFO)

if __name__ == "__main__":
  tf.app.run()
