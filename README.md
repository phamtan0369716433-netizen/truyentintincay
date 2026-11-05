# Project 4: Reliable Transport

## Objectives

* Implement a simple reliable transport protocol.
* Understand the mechanisms required to reliably transfer data
* Understand how different sliding window protocols work

## Getting Started

To start this project, you will first need to get the [infrastructure setup](https://github.com/minlanyu/cs145-site/blob/spring2025/infra.md) and clone this repository with submodules:

```bash
git clone --recurse-submodules "<your repository>"
```

When there are updates to the starter code, TFs will open pull requests in your repository. You should merge the pull request and pull the changes back to local. You might need to resolve conflicts manually (either when merging PR in remote or pulling back to local). However, most of the times there shouldn't be too much conflict as long as you do not make changes to test scripts, infrastructures, etc. Reach out to TF if it is hard to merge.

## Overview

In this project, you will build a simple reliable transport protocol, RTP, **on top of UDP**. Your RTP implementation must provide in­ order, reliable delivery of UDP datagrams in the presence of events like packet loss, delay, corruption, duplication, and re­ordering.

There are a variety of ways to ensure a message is reliably delivered from a sender to a receiver. You are to implement a sender (`sender`) and a receiver (`receiver`) that follows the following RTP specification.

**You will do this project in the same VM as previous projects.**

### UDP sockets

This project is built on top of UDP. You **MUST NOT** use TCP sockets. For background, you can check out [UDP - Client And Server Example Programs In Python](https://pythontic.com/modules/socket/udp-client-server-example). Here's the high-level workflow: At the receiver, you can create a socket and bind it to a specific port. The sender can then create a socket and send traffic directly to the receiver based on its IP and port. (Note, this is the difference with TCP: the sender doesn't need to run `connect` to establish a connection.) Both the sender and the receiver can use `sendto` and `recvfrom` to communicate with each other.

The key is to understand Python socket [`bind`](https://pythontic.com/modules/socket/bind), [`recvfrom`](https://pythontic.com/modules/socket/recvfrom) and [`sendto`](https://pythontic.com/modules/socket/sendto) APIs.

### RTP Specification

RTP sends data in the format of a header, followed by a chunk of data. It has four header types: `START`, `END`, `DATA`, and `ACK`, all following the same format:

```c
struct PacketHeader {
  int type;     // 0: START; 1: END; 2: DATA; 3: ACK
  int seq_num;  // Described below
  int length;   // Length of data; 0 for ACK, START and END packets
  int checksum; // 32-bit CRC
}
```

To initiate a connection, `sender` starts with a `START` packet and waits for an ACK for this `START` packet. You do not have to handle the case in which the `START` ACK is delayed or dropped. After sending the `START` message, additional packets in the same connection are sent using the `DATA` message type, adjusting `seq_num` appropriately. After everything has been transferred, the connection should be terminated with `sender` sending an `END` message and waiting for the corresponding ACK for this message.

For each connection, `seq_num` starts from 0 (i.e., the first `START` packet has `seq_num` 0). The `seq_num` of ACK for `START` is 1. The `seq_num` of `DATA` packets then starts from 1 and gets incremented following the detailed specifications below.

In this project, we use `seq_num` and cumulative `ACK` at the packet level instead of bytes.

### Packet Size

An important limitation is the maximum size of your packets. The UDP protocol has an 8 byte header, and the IP protocol underneath it has a header of 20 bytes. Because we will be using Ethernet networks, which have a maximum frame size of 1500 bytes, this leaves 1472 bytes for your entire `packet` structure (including both the header and the chunk of data).

### Outline

Overall, this project has the following components:

* [Part 1](#part-1-implement-sender): Implement `sender`
* [Part 2](#part-2-implement-receiver): Implement `receiver`
* [Part 3](#part-3-optimizations): Optimizations in `RTP-opt`
* [Submission Instructions](#submission-and-grading)

`RTP-base` and `RTP-opt` contain the exact same copy of scaffolding code. For Part 1 and Part 2 you should modify `RTP-base`. For Part 3 you should modify `RTP-opt`.

> [!NOTE]
> Use `sudo pip install scapy==2.4.0` in the VM to install `scapy` package required for this project.

## Part 1: Implement `sender`

> [!NOTE]
> You should be modifying `RTP-base` for this part.

`sender` should read an input message and transmit it to a specified receiver using UDP sockets following the RTP protocol. It should split the input message into appropriately sized chunks of data, and append a `checksum` to each packet. `seq_num` should increment by one for each additional packet in a connection. Please use the 32-bit CRC header we provide in `sender_receiver/util.py`, in order to add a checksum to your packet.

You will implement reliable transport using a sliding window mechanism. The size of the window (`window-size`) will be specified in the command line. `sender` must accept cumulative `ACK` packets from `receiver`.

After transferring the entire message, you should send an `END` message to mark the end of the connection. Note that the ACK packet of the `END` message might get dropped while the receiver already exited, making a retransmission in vain. To handle this situation, `sender` should start a 500 milliseconds timer once it sends the `END` message. `sender` can exit if (1) it receives the ACK packet of `END` or (2) 500 milliseconds have passed after it sends `END`.

`sender` must ensure reliable data transfer under the following four types of network errors:

- Loss of arbitrary levels;
- Re­ordering of ACK messages;
- Duplication of any amount for any packet;
- Delay in the arrivals of ACKs.

To handle cases where `ACK` packets are lost, you should implement a 500 milliseconds *retransmission timer* to automatically retransmit packets that were never acknowledged. Whenever the window moves forward (i.e., some ACK(s) are received and some new packets are sent out), you reset the timer. If after 500ms the window still has not advanced, you retransmit all packets in the window because they are all never acknowledged.

### Running `sender`

```
usage: sender.py [-h] receiver_ip receiver_port window_size

positional arguments:
  receiver_ip    The IP address of the host that receiver is running on
  receiver_port  The port number on which receiver is listening
  window_size    Maximum number of outstanding packets

options:
  -h, --help     show this help message and exit
```

Note that the sender reads the message to be transferred from stdin. You may want to create a file that contains the message (either text or binary) and redirect stdin to that file. See [testing](#testing-your-solutions-part-1--part-2) for more details.

## Part 2: Implement `receiver`

> [!NOTE]
> You should be modifying `RTP-base` for this part.

`receiver` needs to handle only one `sender` at a time and should ignore `START` messages while in the middle of an existing connection. It must receive and store the message sent by the sender on disk completely and correctly.

`receiver` should also calculate the checksum value for the data in each `packet` it receives using the header mentioned in Part 1. If the calculated checksum value does not match the `checksum` provided in the header, it should drop the packet (i.e. not send an ACK back to the sender).

For each packet received, it sends a cumulative `ACK` with the `seq_num` it expects to receive next. If it expects a packet of sequence number `N`, the following two scenarios may occur:

- If it receives a packet with `seq_num` not equal to `N`, it sends back an `ACK` with `seq_num=N`. Here `receiver` still buffers out-of-order packets.
- If it receives a packet with `seq_num=N`, it will check for the highest sequence number (say `M`) of the in­order packets it has already received and send `ACK` with `seq_num=M+1`.

If the next expected `seq_num` is `N`, `receiver` will drop all packets with `seq_num` greater than or equal to `N + window_size` to maintain a `window_size` window.

`receiver` can exit once it sends the ACK packet of the `END` message.

> [!TIP]
> - You can try to print the state maintained (e.g. sequence number interval of current window) in the sender and receiver.
> - You need to use `sys.stdout.flush()` to force everything in the buffer to the terminal ([learn more](https://stackoverflow.com/questions/10019456/usage-of-sys-stdout-flush-method)).

### Running `receiver`

```
usage: receiver.py [-h] receiver_ip receiver_port window_size

positional arguments:
  receiver_ip    The IP address of the host that receiver is running on
  receiver_port  The port number on which receiver is listening
  window_size    Maximum number of outstanding packets

options:
  -h, --help     show this help message and exit
```

Note that the receiver prints the received message to stdout. You may want to redirect output to a file for comparison with the message sent. See [testing](#testing-your-solutions-part-1--part-2) for more details.

## Testing Your Solutions (Part 1 & Part 2)

We provide a proxy-based testing script to help verify the correctness of your solution. The testing script initiates connections with your receiver and sender separately, and forward packets with random delay, reordering, drops, or modifications. Your solution should pass the testing script for any window size.

> [!NOTE]
> Make sure again that you modified `sender` and `receiver` under `RTP-base` for Part 1 and Part 2 (instead of `RTP-opt`).

For automatic testing, run:

```bash
./test_scripts/test.sh RTP-base
```

For manual testing, there are four steps:

```bash
# Start the receiver
python RTP-base/receiver.py localhost $PORT_RECV $WINDOW_SIZE > RTP-base/output.txt
# Start the proxy
# Run python test_scripts/proxy.py -h to check its usage
python test_scripts/proxy.py localhost $PORT_SEND localhost $PORT_RECV $ERROR_TYPES
# Start the sender
python RTP-base/sender.py localhost $PORT_SEND $WINDOW_SIZE < test_scripts/test_message.txt
# Compare the result
./test_scripts/compare.sh RTP-base/output.txt test_scripts/test_message.txt
```

For instance,

```bash
python RTP-base/receiver.py localhost 40000 128 > RTP-base/output.txt
python test_scripts/proxy.py localhost 50000 localhost 40000 0123
python RTP-base/sender.py localhost 50000 128 < test_scripts/test_message.txt
./test_scripts/compare.sh RTP-base/output.txt test_scripts/test_message.txt
```

In the example above,

- Receiver listens on port 40000;
- Proxy listens on port 50000 (waiting for sender connection) and connects to port 40000 (where the client is listening on); all error types are included (`0123`);
- Sender connects to port 50000 (where the proxy is listening on) and here completes the packet forwarding;
- Compare `RTP-base/output.txt` (output of the receiver) to `test_scripts/test_message.txt` (input to the sender).

> [!NOTE]
> - You may need to delete the old `RTP-base/output.txt` before testing a new solution.
> - If you see errors like *Address already in use*, try `kill -9 $(sudo lsof -ti:$PORT_RECV,$PORT_SEND)`, which, in the example above, would be `kill -9 $(sudo lsof -ti:40000,50000)`.
> - If you see *SUCCESS: Message received matches message sent!* printed, then your solution passes the test!

## Part 3: Optimizations

> [!NOTE]
> You should be modifying `RTP-opt` for this part. You can start by copying your solution in `RTP-base` into `RTP-opt` because we will be making optimizations on top of Part 1 and Part 2.

For this part of the project, you will make a few modifications to the programs written in the previous two sections. Consider how the programs written in the previous sections would behave for the following case where there is a window of size 3:

<img src="images/base_case.png" title="Inefficient transfer of data" alt="" width="250" height="250"/>

In this case `receiver` would send back two ACKs both with the sequence number set to 0 (as this is the next packet it is expecting). This will result in a timeout in `sender` and a retransmission of packets 0, 1 and 2. However, since `receiver` has already received and buffered packets 1 and 2. Thus, there is an unnecessary retransmission of these packets.

In order to account for situations like this, you will be modifying your `receiver` and `sender` accordingly.

> [!NOTE]
> You updated version of the program should be placed in another folder called `RTP-opt`; your previous solution in `RTP-base` should not involve the optimizations.

* `receiver` will not send cumulative ACKs anymore; instead, it will send back an ACK with `seq_num` set to whatever it was in the data packet (i.e., if a sender sends a data packet with `seq_num` set to 2, `receiver` will also send back an ACK with `seq_num` set to 2). It should still drop all packets with `seq_num` greater than or equal to `N + window_size`, where `N` is the next expected `seq_num`.
* `sender` must maintain information about all the ACKs it has received in its current window and maintain a 500 milliseconds *retransmission timer* (Note: just one timer for all packets in the current window) to retransmit packets that were not acknowledged in the current window. So, for example, packet 0 having a timeout would not necessarily result in a retransmission of packets 1 and 2.

For a more concrete example, here is how your improved `sender` and `receiver` should behave for the case described at the beginning of this section:

- `receiver` individually ACKs both packet 1 and 2.
- `sender` receives these ACKs and denotes in its buffer that packets 1 and 2 have been received. Then, the it waits for the 500 ms timeout and only retransmits packet 0 again.

<img src="images/improvement.png" title="only ACK necessary data" alt="" width="250" height="250"/>
<img src="images/improvement_2.png" title="only send unACKd data" alt="" width="250" height="250"/>

## Testing Your Solutions (Part 3)

> [!NOTE]
> Make sure again that you modified `sender` and `receiver` under `RTP-opt` for Part 3 and did not touch your solutions in `RTP-base` for Part 1 and Part 2.

Your code with optimizations in Part 3 should be able to pass the same tests as for [Part 1 and Part 2](#testing-your-solutions-part-1--part-2), except that you need to change all occurrences of `RTP-base` to `RTP-opt`. For automatic testing, run:

```bash
./test_scripts/test.sh RTP-opt
```

For manual testing, please refer to testing instructions for [Part 1 and Part 2](#testing-your-solutions-part-1--part-2).

## Submission and Grading

### Submit your work

You are expected to tag the version you would like us to grade on using following commands and push it to your own repo. You can learn from [this tutorial](https://git-scm.com/book/en/v2/Git-Basics-Tagging) on how to use git tag command. This command will record the time of your submission for our grading purpose.

```bash
git tag -a submission -m "Final Submission"
git push --tags
```

### What to submit

You are expected to submit the following documents:

- The source code `RTP-base/sender.py` and `RTP-base/receiver.py` for Part 1 and Part 2.
- The source code `RTP-opt/sender.py` and `RTP-opt/receiver.py` for Part 3.

### Grading

Your code in both Part 2 (RTP-base) and Part 3 (RTP-opt) should pass our testing scripts with all four types of network errors. The total grades is 100:

- 60: RTP-base passes test
  - 10: built on top of UDP (doesn't use TCP sockets)
  - 15: correctly implement cumulative ACK
  - 15: correctly implement timeout and retransmission
  - 20: correct received message
- 40: RTP-opt passes test
  - 15: doesn't send cumulative ACKs
  - 15: correctly implement timeout and retransmission
  - 10: correct received message
- Deductions based on late policies
- For this project, you are not required to modify the report (but please feel free to include citations and grading notes there).

## Acknowledgements

This programming project is based on UC Berkeley's Project 2 from EE 122: Introduction to Communication Networks, and Johns Hopkins University's Project 2 from EN.601.414/614: Computer Networks.

## Survey

Please fill up the survey when you finish your project: [Survey link](https://forms.gle/Nk9Vq3TZUckkkc8R9).
