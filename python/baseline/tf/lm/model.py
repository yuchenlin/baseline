from baseline.tf.tfy import *
import json

class AbstractLanguageModel(object):

    def __init__(self):
        pass

    def save_using(self, saver):
        self.saver = saver

    def _rnnlm(self, hsz, nlayers, inputs, vsz):

        def attn_cell():
            return tf.contrib.rnn.DropoutWrapper(lstm_cell(hsz), output_keep_prob=self.pkeep)

        cell = tf.contrib.rnn.MultiRNNCell(
            [attn_cell() for _ in range(nlayers)], state_is_tuple=True)

        self.initial_state = cell.zero_state(self.batchsz, tf.float32)
        outputs, state = tf.contrib.rnn.static_rnn(cell, inputs, initial_state=self.initial_state, dtype=tf.float32)
        output = tf.reshape(tf.concat(outputs, 1), [-1, hsz])

        softmax_w = tf.get_variable(
            "softmax_w", [hsz, vsz], dtype=tf.float32)
        softmax_b = tf.get_variable("softmax_b", [vsz], dtype=tf.float32)

        self.logits = tf.nn.xw_plus_b(output, softmax_w, softmax_b, name="logits")
        self.final_state = state

    def save_values(self, basename):
        self.saver.save(self.sess, basename)

    def save(self, basename):
        self.save_md(basename)
        self.save_values(basename)

    def create_loss(self):
        with tf.variable_scope("Loss"):
            targets = tf.reshape(self.y, [-1])
            loss = tf.contrib.legacy_seq2seq.sequence_loss_by_example(
                [self.logits],
                [targets],
                [tf.ones([tf.size(targets)], dtype=tf.float32)])
            loss = tf.reduce_sum(loss) / self.batchsz
            return loss


class WordLanguageModel(AbstractLanguageModel):

    def __init__(self):
        AbstractLanguageModel.__init__(self)

    def make_feed_dict(self, x, xch, y, do_dropout=False):
        pkeep = 1.0 - self.pdrop_value if do_dropout else 1.0
        feed_dict = {self.x: x, self.xch: xch, self.y: y, self.pkeep: pkeep}
        return feed_dict

    def params(self, sess, batchsz, nbptt, maxw, word_vec, hsz, nlayers, pdrop):

        self.sess = sess
        self.x = tf.placeholder(tf.int32, [None, nbptt], name="x")
        self.xch = tf.placeholder(tf.int32, [None, nbptt, maxw], name="xch")
        self.y = tf.placeholder(tf.int32, [None, nbptt], name="y")
        self.pkeep = tf.placeholder(tf.float32, name="pkeep")
        self.pdrop_value = pdrop
        self.batchsz = batchsz
        self.nbptt = nbptt
        self.maxw = maxw
        self.word_vocab = word_vec.vocab

        vsz = word_vec.vsz + 1

        with tf.name_scope("WordLUT"):
            Ww = tf.Variable(tf.constant(word_vec.weights, dtype=tf.float32), name="W")
            we0 = tf.scatter_update(Ww, tf.constant(0, dtype=tf.int32, shape=[1]), tf.zeros(shape=[1, word_vec.dsz]))
            with tf.control_dependencies([we0]):
                wembed = tf.nn.embedding_lookup(Ww, self.x, name="embeddings")

        inputs = tf.nn.dropout(wembed, self.pkeep)
        inputs = tf.unstack(inputs, num=self.nbptt, axis=1)
        self._rnnlm(hsz, nlayers, inputs, vsz)

    def save_md(self, basename):

        path = basename.split('/')
        base = path[-1]
        outdir = '/'.join(path[:-1])

        tf.train.write_graph(self.sess.graph_def, outdir, base + '.graph', as_text=False)
        with open(basename + '.saver', 'w') as f:
            f.write(str(self.saver.as_saver_def()))

        if len(self.word_vocab) > 0:
            with open(basename + '-word.vocab', 'w') as f:
                json.dump(self.word_vocab, f)
        with open(basename + '-batch_dims.json', 'w') as f:
            json.dump({'batchsz': self.batchsz, 'nbptt': self.nbptt, 'maxw': self.maxw}, f)


class CharCompLanguageModel(AbstractLanguageModel):

    def __init__(self):
        AbstractLanguageModel.__init__(self)

    def make_feed_dict(self, x, xch, y, do_dropout=False):
        pkeep = 1.0 - self.pdrop_value if do_dropout else 1.0
        feed_dict = {self.x: x, self.xch: xch, self.y: y, self.pkeep: pkeep}
        return feed_dict

    def params(self, sess, batchsz, nbptt, maxw, vsz, char_vec, filtsz, wsz, hsz, nlayers, pdrop):

        self.sess = sess
        self.x = tf.placeholder(tf.int32, [None, nbptt], name="x")
        self.xch = tf.placeholder(tf.int32, [None, nbptt, maxw], name="xch")
        self.y = tf.placeholder(tf.int32, [None, nbptt], name="y")
        self.pkeep = tf.placeholder(tf.float32, name="pkeep")
        self.char_vocab = char_vec.vocab
        self.batchsz = batchsz
        self.nbptt = nbptt
        self.maxw = maxw
        self.pdrop_value = pdrop
        char_dsz = char_vec.dsz
        Wc = tf.Variable(tf.constant(char_vec.weights, dtype=tf.float32), name="Wch")
        ce0 = tf.scatter_update(Wc, tf.constant(0, dtype=tf.int32, shape=[1]), tf.zeros(shape=[1, char_dsz]))

        with tf.control_dependencies([ce0]):
            xch_seq = tensor2seq(self.xch)
            cembed_seq = []
            for i, xch_i in enumerate(xch_seq):
                cembed_seq.append(shared_char_word_var_fm(Wc, xch_i, filtsz, char_dsz, wsz, None if i == 0 else True))
            word_char = seq2tensor(cembed_seq)

        # List to tensor, reform as (T, B, W)
        # Join embeddings along the third dimension
        joint = word_char

        inputs = tf.nn.dropout(joint, self.pkeep)
        inputs = tf.unstack(inputs, num=nbptt, axis=1)
        self._rnnlm(hsz, nlayers, inputs, vsz)

    def save_md(self, basename):

        path = basename.split('/')
        base = path[-1]
        outdir = '/'.join(path[:-1])
        tf.train.write_graph(self.sess.graph_def, outdir, base + '.graph', as_text=False)
        with open(basename + '.saver', 'w') as f:
            f.write(str(self.saver.as_saver_def()))

        if len(self.char_vocab) > 0:
            with open(basename + '-char.vocab', 'w') as f:
                json.dump(self.char_vocab, f)
        with open(basename + '-batch_dims.json', 'w') as f:
            json.dump(self.batch_info, f)

def create_model(word_vec, char_vec, **kwargs):
    nbptt = kwargs.get('nbptt', 35)
    maxw = kwargs.get('maxw', 100)
    hsz = kwargs.get('hsz')
    unif = kwargs.get('unif')
    batchsz = kwargs.get('batchsz')
    is_char_model = kwargs.get('char', False)
    layers = kwargs.get('layers')
    pdrop = kwargs.get('dropout', 0.5)
    sess = kwargs.get('sess', tf.Session())
    #with tf.Graph().as_default():

    weight_initializer = tf.random_uniform_initializer(-unif, unif)

    lm = None
    with tf.variable_scope('Model', initializer=weight_initializer):
        if is_char_model is True:
            print('Using character-level modeling')
            lm = CharCompLanguageModel()
            filtsz = kwargs['cfiltsz']
            wsz = kwargs.get['wsz']
            lm.params(sess, batchsz, nbptt, maxw, word_vec.vsz + 1, char_vec, filtsz, wsz, hsz, layers, pdrop)
        else:
            print('Using word-level modeling')
            lm = WordLanguageModel()
            lm.params(sess, batchsz, nbptt, maxw, word_vec, hsz, layers, pdrop)
        return lm
