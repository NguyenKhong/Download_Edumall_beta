import Queue
import copy
from var_dump import var_dump

q = Queue.Queue()
for i in xrange(10):
    q.put(i)

l = list(q.queue)

print l

print l[:-1]