from tools.fault_tests import run_leader_crash_test, run_follower_reconnect_test, run_partition_test, run_edgecase_tests

if __name__ == '__main__':
    print('Leader crash test:')
    run_leader_crash_test()
    print('\nFollower reconnect test:')
    run_follower_reconnect_test()
    print('\nPartition test:')
    run_partition_test()
    print('\nEdgecases test:')
    run_edgecase_tests()