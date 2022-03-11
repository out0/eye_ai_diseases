from io import StringIO
from xmlrpc.client import Boolean
from numpy import dtype
import torch
import torch.nn as nn
import torchvision.models as models
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


class EyeClassifierResnet(nn.Module):
    __layers = []
    __device = None
    __optimizer = None
    __loss_function = None

    def __add_layers(self, layers: List[Tuple[nn.Module, TransferFunction]]) -> None:
        for i in range(0, len(layers)):
            self.__layers.append((layers[i][0], layers[i][1]))
            self.add_module(f'layer {i+1}', layers[i][0])

    def __init__(self, num_classes: int) -> None:
        super(EyeClassifierResnet, self).__init__()
    
        self.__add_layers([

            (models.resnet18(), TransferFunction.NotApplicable),

            (nn.Linear(in_features=1000, out_features=84),
             TransferFunction.Relu),

            (nn.Linear(in_features=84, out_features=42),
             TransferFunction.Relu),

            (nn.Linear(in_features=42, out_features=num_classes),
             TransferFunction.NotApplicable),
        ])

    def forward(self, image):
        outp = image
        for layer in self.__layers:
            if (type(layer[0]) == nn.Linear):
                outp = layer[0](outp.view(-1,layer[0].in_features))
            else:
                outp = layer[0](outp)

            tf = EyeClassifierResnet.__get_tf(layer[1])
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
        self.__loss_function = loss_func
        return self


    def train (self, dataset: Dataset, num_epochs:int = 100, batch_size:int = 4, learning_rate:float = 0.01, gpu: Boolean=True, verbose: Boolean = True):
        train_loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

        self.__change_device(gpu)

        optimizer = self.__optimizer
        loss_function = self.__loss_function

        if (optimizer == None):
            optimizer = torch.optim.SGD(self.parameters(), lr=learning_rate)

        if (loss_function == None):
            loss_function = nn.CrossEntropyLoss()

        total_steps = len(train_loader)
        train_percent_step = 0.01*(num_epochs * total_steps)
        train_percent_total = 0
        train_percent_pos = 0

        for epoch in range(num_epochs):
            for i, (images, labels) in enumerate(train_loader):

                device = self.__device
                images = images.to(device)

                for i in range(0, len(labels)):
                    labels[i] = labels[i].to(device)
                labels = labels.to(device)

                #forward
                outputs = self(images)
                loss = loss_function(outputs, labels)
                
                #back-prop.
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                if verbose:
                    if train_percent_pos >= train_percent_step or train_percent_total == 0:
                        train_percent_pos = 0
                        train_percent_total += 1
                        print (f'training ({train_percent_total}%) epoch {epoch+1}/{num_epochs}, loss = {loss.item():.4f}')
                        #print (f'training ({train_percent_total}%) epoch {epoch+1}/{num_epochs}, step {i+1}/{total_steps}, loss = {loss.item():.4f}')
            
                    train_percent_pos += 1    
    
    def test (self, dataset: Dataset, batch_size:int = 4, gpu: Boolean=True, verbose: Boolean = True):
        test_loader = DataLoader(dataset, batch_size=batch_size, shuffle=False)

        self.__change_device(gpu)

        with torch.no_grad():
            n_correct = 0
            n_samples = 0
            n_class_samples = 0

            for images, labels in test_loader:

                device = self.__device
                images = images.to(device)

                for i in range(0, len(labels)):
                    labels[i] = labels[i].to(device)
                labels = labels.to(device)
                
                outp = self(images)
                torch.sigmoid(outp)
                #value, index
                #_, predictions = torch.max(outp, 1)
                predictions = (outp >= 0.5).float()
                n_samples += labels.shape[0] * labels.shape[1]
                m_results = predictions == labels
                n_correct += m_results.sum(0).cpu().numpy()

            sum_correct = n_correct.sum()
            print (f'accuracy: {(100.0 * sum_correct/n_samples):.2f}% [{sum_correct}/{n_samples}]')

            labels = dataset.classes
            num_labels = len(labels)

            total_samples = len(dataset)
            for i in range(0, num_labels):
                acc = 100.0 * (n_correct[i]/total_samples);
                print (f'\t - {labels[i]}: {acc:.2f}% [{n_correct[i]}/{total_samples}]')
