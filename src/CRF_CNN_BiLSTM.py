import theano
import theano.tensor as T
import numpy as np
import CRF_PP_With_Type as CRFPP
from theano.sandbox.rng_mrg import MRG_RandomStreams as RandomStreams

class CRF_CNN_BiLSTM:
    def __init__(self, orthogonal_weight_init, w2v_matrix, word_embedding_dim, n_characters, char_embedding_dim, n_pos, pos_embedding_dim, max_token_length, 
                 n_filter, filter_width, 
                 cnn_output_dim, lstm_hidden_dim2, lstm_hidden_dim, output_dim, mlp_dim, 
                 train_words, train_lengths, train_targets, train_char_samples, train_pos,
                 test_words, test_lengths, test_targets, test_char_samples, testing_char_lengths, test_pos,
                 gradient_threshold,  
                 highway_network_enable):
        self.orthogonal_weight_init = orthogonal_weight_init
        self.word_embedding_dim = word_embedding_dim
        self.n_characters = n_characters
        self.char_embedding_dim = char_embedding_dim
        self.n_pos = n_pos
        self.pos_embedding_dim = pos_embedding_dim
        self.max_token_length = max_token_length
        self.n_filter = n_filter
        self.filter_width = filter_width
        self.cnn_output_dim = cnn_output_dim
        self.lstm_hidden_dim = lstm_hidden_dim
        self.lstm_hidden_dim2 = lstm_hidden_dim2
        self.output_dim = output_dim
        self.mlp_dim = mlp_dim
        self.n_labels = output_dim
        self.gradient_threshold = gradient_threshold
        self.highway_network_enable = highway_network_enable
        self.PP_output_dim = output_dim
        self.filter_shapes = []
        self.pool_shapes = []
        self.n_rnn_matrix = 4
        self._eps = 1e-5
        self.dropout_p = 0.5
        
        cnn_output_dim = 30
        self.cnn_output_dim = cnn_output_dim 
        n_filter = [30]
        self.n_filter = n_filter 
        self.filter_width = [3]
        char_embedding_dim = 30
        self.char_embedding_dim = char_embedding_dim
        
        print 'Welcome to CRF_CNN_BiLSTM'
        print 'CNN filters = ', n_filter
        print 'CNN output dimension = ', cnn_output_dim
        print 'n_characters = ', n_characters
        print 'Dropout on = ', self.dropout_p
        self.char_embedding_dim = char_embedding_dim 

        F = []
        for i, width in enumerate(self.filter_width):
            filter_shape = (n_filter[i], 1, char_embedding_dim, width)
            self.filter_shapes.append(filter_shape)
            pool_shape = (1,max_token_length-width+1)
            self.pool_shapes.append(pool_shape)
            F.append(np.random.uniform(-0.05, 0.05, (n_filter[i], 1, char_embedding_dim, width)))
            print filter_shape, pool_shape
        
        P = np.random.uniform(-0.99, 0.99, (n_characters, char_embedding_dim)).astype(theano.config.floatX)
        
        unary_input_dim = word_embedding_dim
        unary_input_dim += cnn_output_dim
        self.unary_input_dim = unary_input_dim  
        
        U = np.random.uniform(-np.sqrt(6./np.sum([unary_input_dim, lstm_hidden_dim])), np.sqrt(6./np.sum([unary_input_dim, lstm_hidden_dim])), (2*self.n_rnn_matrix, unary_input_dim, lstm_hidden_dim))
        W = np.random.uniform(-np.sqrt(6./np.sum([lstm_hidden_dim, lstm_hidden_dim])), np.sqrt(6./np.sum([lstm_hidden_dim, lstm_hidden_dim])), (2*self.n_rnn_matrix, lstm_hidden_dim, lstm_hidden_dim))

        b = np.zeros((2*self.n_rnn_matrix, lstm_hidden_dim), dtype=theano.config.floatX)
        b[0] = np.float32(1.)
        b[self.n_rnn_matrix] = np.float32(1.)
        
        V_input_dim = 2*lstm_hidden_dim
        V = np.random.uniform(-np.sqrt(6./np.sum([V_input_dim, output_dim])), np.sqrt(6./np.sum([V_input_dim, output_dim])), (V_input_dim, output_dim))
        c = np.zeros((output_dim,), dtype=theano.config.floatX)
                            
        print 'In CRF_CNN_BiLSTM'
        print 'Params initialized...'

        self.E = theano.shared(name='E', value=w2v_matrix.astype(theano.config.floatX), borrow=True)

        self.F = []
        for i, _ in enumerate(self.filter_width):
            self.F.append(theano.shared(value=F[i].astype(theano.config.floatX), borrow=True))
        self.P = theano.shared(name='P', value=P.astype(theano.config.floatX), borrow=True)

        self.U = theano.shared(name='U', value=U.astype(theano.config.floatX), borrow=True)
        self.W = theano.shared(name='W', value=W.astype(theano.config.floatX), borrow=True)
        self.b = theano.shared(name='b', value=b.astype(theano.config.floatX), borrow=True)

        self.V = theano.shared(name='V', value=V.astype(theano.config.floatX), borrow=True)
        self.c = theano.shared(name='c', value=c.astype(theano.config.floatX), borrow=True)
              
        self.test_words = theano.shared(value=test_words.astype('int32'), borrow=True)
        self.test_lengths = theano.shared(value=test_lengths.astype('int32'), borrow=True)
        self.test_targets = theano.shared(value=test_targets.astype('int32'), borrow=True)
        self.test_char_samples = theano.shared(value=test_char_samples.astype('int32'), borrow=True)

        self.train_words = theano.shared(value=train_words.astype('int32'), borrow=True)
        self.train_lengths = theano.shared(value=train_lengths.astype('int32'), borrow=True)
        self.train_targets = theano.shared(value=train_targets.astype('int32'), borrow=True)
        self.train_char_samples = theano.shared(value=train_char_samples.astype('int32'), borrow=True)
                
        self.srng = RandomStreams(seed=2357)
        
        print 'N labels = ', self.n_labels
        self.crf = CRFPP.CRF_Fx(self.n_labels)
        
        self.build()
        
        print 'Train Graph Generated ...'
        
        self.test_build()
        print 'Test Graph Generated ...'
    
    def getName(self):
        return 'CNN_BiLSTM_CRF'
        
    def clip_norms(self, gs, c):
        norm = T.sqrt(T.sum([T.sum(g**2) for g in gs]))
        return [T.switch(T.ge(norm, c), g*c/norm, g) for g in gs]
            
    def glorot_weight_initialization(self, n, row_ndim, col_ndim):
        if n > 0:
            W = np.random.uniform(-np.sqrt(6./np.sum([row_ndim, col_ndim])), np.sqrt(6./np.sum([row_ndim, col_ndim])), (n, row_ndim, col_ndim))
        else:
            W = np.random.uniform(-np.sqrt(6./np.sum([row_ndim, col_ndim])), np.sqrt(6./np.sum([row_ndim, col_ndim])), (row_ndim, col_ndim))
        return W
    
    def unary_character_cnn_step(self, x_t):
        char_embeds = self.P[x_t]
        char_embeds2d = T.shape_padleft(char_embeds.T, 2)
        
        pooled_out = []
        for i, _ in enumerate(self.filter_width):
            conv_out = T.tanh(T.nnet.conv2d(input=char_embeds2d, filters=self.F[i], filter_shape=self.filter_shapes[i], input_shape=(1,1,self.char_embedding_dim, self.max_token_length)))
            pooled_out.append(T.signal.pool.pool_2d(conv_out, ws=self.pool_shapes[i], ignore_border=False))
        
        o_pooled = T.concatenate(pooled_out, axis=1)
                        
        wo = T.cast(T.flatten(o_pooled), theano.config.floatX)
            
        return wo

    def LSTM(self, x_t, s_t, c_t, U_f, U_i, U_o, U_c, W_f, W_i, W_o, W_c, b_f, b_i, b_o, b_c):
        x_t = T.cast(x_t, theano.config.floatX)
        s_t = T.cast(s_t, theano.config.floatX)
        f = T.nnet.sigmoid(T.dot(x_t, U_f) + T.dot(s_t, W_f) + b_f)
        i = T.nnet.sigmoid(T.dot(x_t, U_i) + T.dot(s_t, W_i) + b_i)
        o = T.nnet.sigmoid(T.dot(x_t, U_o) + T.dot(s_t, W_o) + b_o)
        _c = T.tanh(T.dot(x_t, U_c) + T.dot(s_t, W_c) + b_c)
        cell = i*_c + f*c_t
        s = o*T.tanh(cell)
        return s, cell

    def LSTM_Dropout(self, x_t, s_t, c_t, U_f, U_i, U_o, U_c, W_f, W_i, W_o, W_c, b_f, b_i, b_o, b_c):
        x_t = T.cast(x_t, theano.config.floatX)
        s_t = T.cast(s_t, theano.config.floatX)
        dropout_x_mask = self.srng.binomial(n=1, size=(self.unary_input_dim,), p=self.dropout_p, dtype='floatX')
        x_t = T.cast(x_t * dropout_x_mask, theano.config.floatX)
        f = T.nnet.sigmoid(T.dot(x_t, U_f) + T.dot(s_t, W_f) + b_f)
        i = T.nnet.sigmoid(T.dot(x_t, U_i) + T.dot(s_t, W_i) + b_i)
        o = T.nnet.sigmoid(T.dot(x_t, U_o) + T.dot(s_t, W_o) + b_o)
        _c = T.tanh(T.dot(x_t, U_c) + T.dot(s_t, W_c) + b_c)
        cell = i*_c + f*c_t
        s = o*T.tanh(cell)
        return s, cell

    def build(self):
        indexes = T.ivector('indexes')
        word_sentences = T.imatrix('word_sentences')
        lengths = T.ivector('lengths')
        labels = T.imatrix('labels')
        char_sentences = T.itensor3('char_sentences')

        params_u = [self.U, self.W, self.V]
        params_u += [self.b, self.c]
        params_u += self.F
        params_u += self.crf.params
        params = params_u
        
        def SentenceStep(word_sentence, length, label_sequence, char_sentence=None):
            word_sentence = word_sentence[:length]
            label_sequence = label_sequence[:length]
            token_sentence = char_sentence[:length]

            token_cnn_sequence, _ = theano.scan(fn=self.unary_character_cnn_step, sequences=token_sentence)
            input = T.cast(T.concatenate([token_cnn_sequence, self.E[word_sentence]], axis=1), theano.config.floatX)

            forward_lstm_input = input
            backward_lstm_input = input[::-1]
            
            init_state = np.zeros((self.lstm_hidden_dim,), dtype=theano.config.floatX)
            init_cell = np.zeros((self.lstm_hidden_dim,), dtype=theano.config.floatX)
            
            [f_s, f_c], _ = theano.scan(fn=self.LSTM_Dropout, 
                                        sequences=forward_lstm_input,
                                        outputs_info=[init_state, 
                                                      init_cell],
                                        non_sequences=[self.U[0],self.U[1],self.U[2],self.U[3],
                                                       self.W[0],self.W[1],self.W[2],self.W[3],
                                                       self.b[0],self.b[1],self.b[2],self.b[3]
                                                       ])
 
            [b_s, b_c], _ = theano.scan(fn=self.LSTM_Dropout, 
                                        sequences=backward_lstm_input,
                                        outputs_info=[init_state, 
                                                      init_cell],                                                       
                                        non_sequences=[self.U[4],self.U[5],self.U[6],self.U[7],
                                                       self.W[4],self.W[5],self.W[6],self.W[7],
                                                       self.b[4],self.b[5],self.b[6],self.b[7]
                                                       ])                
                
            s1 = T.cast(T.concatenate([f_s, b_s[::-1]], axis=1), theano.config.floatX)
            unary = T.dot(s1, self.V) + self.c 

            loss = self.crf.fprop(unary, label_sequence, mode='train')
            loss_u = loss
            loss_pp = loss
            
            return loss, loss_u, loss_pp
        
        scan_input = [word_sentences, lengths, labels]
        scan_input.append(char_sentences)
        [_loss, _loss_u, _loss_pp], _ = theano.scan(fn=SentenceStep, sequences=scan_input)

        loss = T.mean(_loss)
        loss_u = T.mean(_loss_u)
        loss_pp = T.mean(_loss_pp)  
        
        dLoss_dP = T.sqrt(T.sum(T.grad(loss, self.P)**2))

        updates, norm, pp_norm = self.adam(loss, params, learning_rate=0.001, b1=0.9, b2=0.999, e=1e-6, gamma=1-1e-8, gradient_threshold=self.gradient_threshold)
        self.trainer = theano.function([indexes],
                                       [loss, norm, pp_norm, loss_u, loss_pp, dLoss_dP], 
                                       updates=updates, 
                                       allow_input_downcast=True,
                                       givens={
                                           word_sentences : self.train_words[indexes], 
                                           lengths : self.train_lengths[indexes], 
                                           char_sentences : self.train_char_samples[indexes],
                                           labels : self.train_targets[indexes]
                                       })

    def test_build(self):
        index = T.iscalar('index')
        word_sentences = T.ivector('word_sentences')
        length = T.iscalar('length')
        char_sentences = T.imatrix('char_sentences')
        token_sentence = char_sentences[:length]

        word_sentence = word_sentences[:length]

        token_cnn_sequence, _ = theano.scan(fn=self.unary_character_cnn_step, sequences=token_sentence)
        input = T.cast(T.concatenate([token_cnn_sequence, self.E[word_sentence]], axis=1), theano.config.floatX)

        forward_lstm_input = input
        backward_lstm_input = input[::-1]
 
        init_state = np.zeros((self.lstm_hidden_dim,), dtype=theano.config.floatX)
        init_cell = np.zeros((self.lstm_hidden_dim,), dtype=theano.config.floatX)
        
        [f_s, f_c], _ = theano.scan(fn=self.LSTM, 
                                    sequences=forward_lstm_input,
                                    outputs_info=[init_state, 
                                                  init_cell],
                                    non_sequences=[self.U[0],self.U[1],self.U[2],self.U[3],
                                                   self.W[0],self.W[1],self.W[2],self.W[3], 
                                                   self.b[0],self.b[1],self.b[2],self.b[3]
                                                   ])
 
        [b_s, b_c], _ = theano.scan(fn=self.LSTM, 
                                    sequences=backward_lstm_input,
                                    outputs_info=[init_state, 
                                                  init_cell],                                                       
                                    non_sequences=[self.U[4],self.U[5],self.U[6],self.U[7],
                                                   self.W[4],self.W[5],self.W[6],self.W[7],
                                                   self.b[4],self.b[5],self.b[6],self.b[7]
                                                   ])                
            
        s1 = T.cast(T.concatenate([f_s, b_s[::-1]], axis=1), theano.config.floatX)
        unary = T.dot(s1, self.V) + self.c 

        prediction = self.crf.fprop(unary, ground_truth=None, viterbi=True, return_best_sequence=True, mode='eval')

        self.testing = theano.function([index],
                                       [prediction, unary, unary], 
                                       allow_input_downcast=True,
                                       givens={
                                           word_sentences : self.test_words[index], 
                                           length : self.test_lengths[index], 
                                           char_sentences : self.test_char_samples[index]
                                       })


    def train(self, indexes):
        loss, norm, pp_norm, loss_u, loss_pp, P_g = self.trainer(indexes)
        return loss, norm, pp_norm, loss_u, loss_pp, P_g

    def testing(self, index):
        prediction, unary_score, pp_score = self.testing(index)
        return prediction, unary_score, pp_score
                              
    def get_parameters(self):
        return self.crf.transition_matrix.get_value()

    def gradient_norm(self, gs):
        norm = T.sum([T.sqrt(T.sum(g**2)) for g in gs])
        return norm

    def clip_norms(self, gs, norm, c):
        return [theano.ifelse.ifelse(T.ge(norm, c), g*c/norm, g) for g in gs]
    
    def momentum(self, loss, all_params, learning_rate=0.01, momentum=0.9):
        updates = []
        all_grads = T.grad(loss, all_params)
        all_grads = clip_norms(all_grads, 50.)
        for p, g in zip(all_params, all_grads):
            m = theano.shared(np.zeros(p.get_value().shape, dtype=theano.config.floatX).astype(theano.config.floatX))
            v = (momentum*m) - (learning_rate*g)

            updates.append((m, v))
            updates.append((p, p + v))

        return updates

    def adam(self, loss, all_params, learning_rate=0.001, b1=0.9, b2=0.999, e=1e-6, gamma=1-1e-8, gradient_threshold=10.0):
        updates = []
        all_grads = T.grad(loss, all_params)
        norm = self.gradient_norm(all_grads)
        pp_norm = T.sqrt(T.sum(T.grad(loss, self.V)**2))
        print 'gradient norm threshold = ', gradient_threshold
        all_grads = self.clip_norms(all_grads, norm, gradient_threshold)
        alpha = learning_rate
        t = theano.shared(np.float32(1.).astype(theano.config.floatX))
        b1_t = b1*gamma**(t-1.)   #(Decay the first moment running average coefficient)
    
        for theta_previous, g in zip(all_params, all_grads):
            m_previous = theano.shared(np.zeros(theta_previous.get_value().shape, dtype=theano.config.floatX).astype(theano.config.floatX))
            v_previous = theano.shared(np.zeros(theta_previous.get_value().shape, dtype=theano.config.floatX).astype(theano.config.floatX))
            
            m = b1_t*m_previous + (1. - b1_t)*g                             # (Update biased first moment estimate)
            v = b2*v_previous + (1. - b2)*g**2.                              # (Update biased second raw moment estimate)
            m_hat = m / (1.-b1**t)                                          # (Compute bias-corrected first moment estimate)
            v_hat = v / (1.-b2**t)                                          # (Compute bias-corrected second raw moment estimate)
            theta = theta_previous - (alpha * m_hat) / (T.sqrt(v_hat) + e) #(Update parameters)
    
            updates.append((m_previous, m))
            updates.append((v_previous, v))
            updates.append((theta_previous, theta))
        updates.append((t, t + 1.))
        
        return updates, norm, pp_norm
    