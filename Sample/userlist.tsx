<div className='space-y-6'>
      {/* HEADER */}
      <div className='flex items-center justify-between'>
        <div>
          <h1 className='text-2xl font-bold tracking-tight text-[rgb(var(--foreground))]'>
            User Management
          </h1>

          <p className='mt-1 text-sm text-[rgb(var(--foreground-muted))]'>
            Review and manage CHSS staffs.
          </p>
        </div>

        <Can perform='user:create'>
          <Button onClick={() => void navigate({ to: '/users/new' })}>Add User</Button>
        </Can>
      </div>

      {/* SEARCH INPUT */}
      <div className='flex flex-wrap items-center justify-between gap-4 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-4'>
        <Input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          placeholder='Search by name or email...'
          aria-label='Search users'
          className='w-full'
        />
      </div>

      {/* TABLE */}
      <div className='flex flex-col space-y-4'>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>First Name</TableHead>
              <TableHead>Last Name</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Status</TableHead>
              <TableHead isNumeric>Actions</TableHead>
            </TableRow>
          </TableHeader>

          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={6}>Loading users...</TableCell>
              </TableRow>
            ) : isError ? (
              <TableRow>
                <TableCell colSpan={6}>Failed to load users.</TableCell>
              </TableRow>
            ) : users.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6}>No users found.</TableCell>
              </TableRow>
            ) : (
              users.map((user: User) => (
                <TableRow key={user.id}>
                  <TableCell>{user.first_name}</TableCell>

                  <TableCell>{user.last_name}</TableCell>

                  <TableCell>{user.email}</TableCell>

                  <TableCell>{user.role.name}</TableCell>

                  <TableCell>{user.status}</TableCell>

                  <TableCell className='space-x-3 text-right'>
                    <Can perform='user:update'>
                      <Button
                        size={'sm'}
                        onClick={() => void navigate({ to: `/users/${user.id}/edit` })}
                      >
                        Edit
                      </Button>
                    </Can>

                    <Can perform='user:delete'>
                      <Button
                        size={'sm'}
                        variant='danger'
                        onClick={() => {
                          handleDeleteClick(user);
                        }}
                      >
                        Delete
                      </Button>
                    </Can>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>

        {/* PAGINATION */}
        <TablePagination>
          <TablePaginationInfo total={total} pageSize={pageSize} onPageSizeChange={setPageSize} />

          <div className='flex items-center gap-2'>
            <Button
              variant='outline'
              size='sm'
              disabled={page === 1}
              onClick={() => {
                setPage((p) => p - 1);
              }}
            >
              <ChevronLeft size={16} />
            </Button>

            <Button
              variant='outline'
              size='sm'
              disabled={page === totalPages || totalPages === 0}
              onClick={() => {
                setPage((p) => p + 1);
              }}
            >
              <ChevronRight size={16} />
            </Button>
          </div>
        </TablePagination>
      </div>

      {/* MODAL */}
      {selectedUser && (
        <DeleteModal
          isOpen={isModalOpen}
          title={'User'}
          name={`${selectedUser.first_name} ${selectedUser.last_name}`}
          onConfirm={handleConfirmDelete}
          onClose={() => {
            setIsModalOpen(false);
            setSelectedUser(null);
          }}
        />
      )}
    </div>
