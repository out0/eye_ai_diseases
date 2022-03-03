from io import StringIO
from xmlrpc.client import Boolean
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from enum import Enum, IntEnum, unique, auto
from typing import Tuple, List, Union

@unique
class TransferFunction(IntEnum):
    NotApplicable = 0
    Sigmoid = 1
    Tanh = 2
    Relu = 3
    LeakyRelu = 4
    Softmax = 5


class EyeClassifier(nn.Module):
    __layers = []
    __device = None
    __optimizer = None
    __loss_func = None

    def __add_layers(self, image_shape: Tuple[int, int, int], layers: List[Tuple[nn.Module, TransferFunction]]) -> None:

        next_layer_shape = image_shape
        for i in range(0, len(layers)):

            if type(layers[i][0]) is nn.Conv2d:
                layers[i][0].in_channels = next_layer_shape[2]
                p = EyeClassifier.__conv_output_shape((next_layer_shape[0],next_layer_shape[1]), kernel_size=5, stride=1, pad=0, dilation=1)
                next_layer_shape[0] = p[0]
                next_layer_shape[1] = p[1]
                next_layer_shape[2] = layers[i][0].out_channels

            elif type(layers[i][0]) is nn.MaxPool2d:
                p = EyeClassifier.__conv_output_shape((next_layer_shape[0],next_layer_shape[1]), kernel_size=5, stride=1, pad=0, dilation=1)
                next_layer_shape[0] = p[0]
                next_layer_shape[1] = p[1]

            elif type(layers[i][0]) is nn.Linear:
                layers[i][0].in_features = next_layer_shape[0] * next_layer_shape [1]
                next_layer_shape = (layers[i][0].out_features, 1)

            self.__layers.append(layers[i][0])
            self.add_module(f'layer {i+1}', layers[i][0])

    def __conv_output_shape(h_w: Tuple[int, int], kernel_size: int, stride: int, pad: int, dilation: int) -> Tuple[int, int]:
            """
            Utility function for computing output of convolutions
            takes a tuple of (h,w) and returns a tuple of (h,w)
            """

            if type(h_w) is not tuple:
                h_w = (h_w, h_w)

            if type(kernel_size) is not tuple:
                kernel_size = (kernel_size, kernel_size)

            if type(stride) is not tuple:
                stride = (stride, stride)

            if type(pad) is not tuple:
                pad = (pad, pad)

            h = (h_w[0] + (2 * pad[0]) - (dilation *
                (kernel_size[0] - 1)) - 1) // stride[0] + 1
            w = (h_w[1] + (2 * pad[1]) - (dilation *
                (kernel_size[1] - 1)) - 1) // stride[1] + 1

            return (w, h)

    def __init__(self, image_shape: Tuple[int, int, int]) -> None:
        super(EyeClassifier, self).__init__()
    
        self.__add_layers(image_shape, [

            (nn.Conv2d(in_channels=image_shape[2], out_channels=6,
                       kernel_size=(5, 5), stride=(1, 1), padding=(0, 0), dilation=(1, 1)),
             TransferFunction.NotApplicable),

            (nn.MaxPool2d(
                kernel_size=(2, 2), stride=(1, 1), padding=(0, 0), dilation=(1, 1)),
             TransferFunction.NotApplicable),

            (nn.Conv2d(in_channels=6, out_channels=16,
                       kernel_size=(5, 5), stride=(1, 1), padding=(0, 0), dilation=(1, 1)),
             TransferFunction.NotApplicable),

            (nn.MaxPool2d(
                kernel_size=(2, 2), stride=(1, 1), padding=(0, 0), dilation=(1, 1)),
             TransferFunction.NotApplicable),

            (nn.Dropout(),
             TransferFunction.NotApplicable),

            (nn.Linear(in_features=400, out_features=84),
             TransferFunction.Relu),

            (nn.Linear(in_features=84, out_features=42),
             TransferFunction.Relu),

            (nn.Linear(in_features=42, out_features=10),
             TransferFunction.NotApplicable),
        ])

    def forward(self, image):
        outp = image
        for layer in self.__layers:
            outp = layer[0](outp)
            tf = EyeClassifier.__get_tf(layer[1])
            if tf != None:
                outp = tf(outp)
        return outp

    def __get_tf(tf_type: TransferFunction):
        if tf_type == TransferFunction.Sigmoid:
            return nn.Sigmoid()
        elif tf_type == TransferFunction.Relu:
            return nn.ReLU()
        elif tf_type == TransferFunction.LeakyRelu:
            return nn.LeakyReLU()
        elif tf_type == TransferFunction.Softmax:
            return nn.Softmax()
        elif tf_type == TransferFunction.Tanh:
            return nn.Tanh()
        else: return None

    def __change_device(self, gpu : Boolean = True):
        if gpu and torch.cuda.is_available():
            self.__device = torch.device('cuda')
        else:
            self.__device = torch.device('cpu')
        self.to(self.__device)

    def set_optimizer(self, optimizer):
        self.__optimizer = optimizer
        return self

    def set_loss_function(self, loss_func):
        self.__loss_func = loss_func
        return self

    def train (self, dataset: Dataset, num_epochs:int = 100, batch_size:int = 4, learning_rate:float = 0.01, gpu: Boolean=True, verbose: Boolean = True):
        train_loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

        self.__change_device(gpu)

        if (self.__optimizer == None):
            self.__optimizer = torch.optim.SGD(self.parameters(), lr=learning_rate)

        if (self.__loss_func == None):
            self.__loss_func = nn.CrossEntropyLoss()

        total_steps = len(train_loader)
        train_percent_step = 0.01*(num_epochs * total_steps)
        train_percent_total = 0
        train_percent_pos = 0

        for epoch in range(num_epochs):
            for i, (images, labels) in enumerate(train_loader):
                # images: 100 x 1 x 28 x 28
                # should be 100 x 784
                # to(device) -> pushes to gpu if available
                images = images.to(self.__device)
                labels = labels.to(self.__device)

                #forward
                outputs = self(images)
                loss = self.__loss_func(outputs, labels)
                
                #back-prop.
                self.__optimizer.zero_grad()
                loss.backward()
                self.__optimizer.step()

                if verbose:
                    if train_percent_pos >= train_percent_step:
                        train_percent_pos = 0
                        train_percent_total += 1
                        print (f'training ({train_percent_total}%\) epoch {epoch+1}/{num_epochs}, step {i+1}/{total_steps}, loss = {loss.item():.4f}')
            
                    train_percent_pos += 1    
    
    def test (self, dataset: Dataset, labels:List[str], batch_size:int = 4, gpu: Boolean=True, verbose: Boolean = True):
        test_loader = DataLoader(dataset, batch_size=batch_size, shuffle=False)

        self.__change_device(gpu)
        num_labels = len(labels)

        with torch.no_grad():
            n_correct = 0
            n_samples = 0
            n_class_correct = [0 for i in range(num_labels)]
            n_class_samples = [0 for i in range(num_labels)]
            for images, labels in test_loader:
                images = images.to(self.__device)
                labels = labels.to(self.__device)
                outp = self(images)

                #value, index
                _, predictions = torch.max(outp, 1)
                n_samples += labels.shape[0]
                n_correct += (predictions == labels).sum().item()

                for i in range(batch_size):
                    label = labels[i]
                    pred = predictions[i]
                    if (label == pred):
                        n_class_correct[label] += 1
                    n_class_samples[label] += 1

            acc = 100.0 * (n_correct/n_samples);
            print (f'accuracy: {acc}% [{n_correct}/{n_samples}')

            for i in range(10):
                acc = 100.0 * (n_class_correct[i]/n_class_samples[i]);
                print (f'accuracy of {labels[i]}: {acc}% [{n_class_correct[i]}/{n_class_samples[i]}]')