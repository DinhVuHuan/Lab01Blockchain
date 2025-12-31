import multiprocessing
import time

from tests.test_replicate_functional import test_probe_success, test_higher_term


def run_func(func, return_dict, key):
    try:
        return_dict[key] = func()
    except Exception as e:
        return_dict[key] = f"EXCEPTION: {e}"


if __name__ == '__main__':
    manager = multiprocessing.Manager()
    results = manager.dict()

    p1 = multiprocessing.Process(target=run_func, args=(test_probe_success, results, 'probe'))
    p2 = multiprocessing.Process(target=run_func, args=(test_higher_term, results, 'higher'))

    p1.start()
    p1.join(timeout=5)
    if p1.is_alive():
        print('probe test timed out; terminating')
        p1.terminate()
        p1.join()
        results['probe'] = 'TIMEOUT'

    p2.start()
    p2.join(timeout=5)
    if p2.is_alive():
        print('higher-term test timed out; terminating')
        p2.terminate()
        p2.join()
        results['higher'] = 'TIMEOUT'

    print('Results:', dict(results))
